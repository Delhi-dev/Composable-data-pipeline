"""Secure, version-aware OECD CbC XML ingestion into the PostgreSQL XML source model."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from lxml import etree
from psycopg2 import errors

from .database import PostgreSQLDatabase, PostgreSQLSession

V1 = "urn:oecd:ties:cbc:v1"
V2 = "urn:oecd:ties:cbc:v2"
PARSER_VERSION = "cbcr-xml-ingestor/1.0"


@dataclass(frozen=True)
class IngestionResult:
    path: Path
    status: str
    xml_document_id: int | None
    message_spec_id: int | None = None
    detail: str | None = None


def local(element: etree._Element | None, name: str | None = None) -> str | bool:
    value = etree.QName(element).localname if element is not None and isinstance(element.tag, str) else ""
    return value == name if name else value


def children(element: etree._Element, name: str) -> list[etree._Element]:
    return [x for x in element if local(x, name)]


def child(element: etree._Element, name: str) -> etree._Element | None:
    return next(iter(children(element, name)), None)


def text(element: etree._Element | None, name: str | None = None) -> str | None:
    if name:
        element = child(element, name) if element is not None else None
    return element.text.strip() if element is not None and element.text and element.text.strip() else None


def decimal(element: etree._Element | None) -> Decimal | None:
    value = text(element)
    return Decimal(value) if value is not None else None


class CbcrXmlIngestor:
    def __init__(self, database: PostgreSQLDatabase, v2_schema: Path, v1_schema: Path | None = None):
        self.database = database
        self.schemas = {V2: etree.XMLSchema(etree.parse(str(v2_schema)))}
        if v1_schema:
            self.schemas[V1] = etree.XMLSchema(etree.parse(str(v1_schema)))

    def ingest_path(self, location: Path) -> list[IngestionResult]:
        paths = [location] if location.is_file() else sorted(location.rglob("*.xml"))
        return [self.ingest_file(path) for path in paths]

    def ingest_file(self, path: Path) -> IngestionResult:
        raw = path.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
        document = self._stage(path, raw, digest)
        if document["duplicate"]:
            return IngestionResult(path, "duplicate", document["id"], detail="identical SHA-256 already staged")
        doc_id = document["id"]
        try:
            parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
            root = etree.fromstring(raw, parser=parser)
        except etree.XMLSyntaxError as exc:
            self._finish(doc_id, "parse_failed", [("fatal", "XML_SYNTAX", None, exc.lineno, exc.offset, str(exc))])
            return IngestionResult(path, "parse_failed", doc_id, detail="malformed XML")
        namespace = etree.QName(root).namespace
        version = root.get("version") or ("1.0.1" if namespace == V1 else "2.0" if namespace == V2 else "unknown")
        self._set_version(doc_id, version)
        schema = self.schemas.get(namespace)
        if schema is None:
            self._finish(doc_id, "schema_invalid", [("fatal", "UNSUPPORTED_SCHEMA", None, None, None, f"No configured XSD bundle for {namespace!r} / {version}")])
            return IngestionResult(path, "schema_invalid", doc_id, detail="unsupported schema version")
        if not schema.validate(root):
            issues = [("error", "XSD_VALIDATION", None, e.line, e.column, e.message) for e in schema.error_log]
            self._finish(doc_id, "schema_invalid", issues)
            return IngestionResult(path, "schema_invalid", doc_id, detail="XSD validation failed")
        try:
            with self.database.transaction() as db:
                message_id = self._map(root, doc_id, db)
                db.execute("UPDATE cbcr_staging.xml_document SET parse_status='parsed',parser_version=%s,parsed_at=clock_timestamp() WHERE xml_document_id=%s", (PARSER_VERSION, doc_id))
                self._attempt(db, doc_id, "parsed", "message graph committed")
            return IngestionResult(path, "parsed", doc_id, message_id)
        except Exception as exc:
            self._finish(doc_id, "parse_failed", [("fatal", "MAP_OR_DATABASE", None, None, None, str(exc))])
            return IngestionResult(path, "parse_failed", doc_id, detail=str(exc))

    def _stage(self, path: Path, raw: bytes, digest: str) -> dict:
        with self.database.transaction() as db:
            existing = db.one("SELECT xml_document_id, parse_status FROM cbcr_staging.xml_document WHERE content_sha256=%s", (digest,))
            if existing:
                if existing["parse_status"] == "parsed":
                    self._attempt(db, existing["xml_document_id"], "duplicate", "identical SHA-256")
                    return {"id": existing["xml_document_id"], "duplicate": True}
                self._attempt(db, existing["xml_document_id"], "started", "retrying previously unparsed payload")
                return {"id": existing["xml_document_id"], "duplicate": False}
            row = db.one("""INSERT INTO cbcr_staging.xml_document(source_file_name,source_uri,content_sha256,xml_schema_version,raw_payload,content_size_bytes,parse_status,parser_version)
                VALUES(%s,%s,%s,'unknown',%s,%s,'received',%s) RETURNING xml_document_id""", (path.name, str(path), digest, raw, len(raw), PARSER_VERSION))
            self._attempt(db, row["xml_document_id"], "started", "payload staged")
            return {"id": row["xml_document_id"], "duplicate": False}

    def _attempt(self, db: PostgreSQLSession, doc_id: int, outcome: str, message: str) -> None:
        db.execute("""INSERT INTO cbcr_staging.xml_ingestion_attempt(xml_document_id,attempt_ordinal,parser_version,outcome,completed_at,message)
          VALUES(%s,(SELECT coalesce(max(attempt_ordinal),0)+1 FROM cbcr_staging.xml_ingestion_attempt a WHERE a.xml_document_id=%s),%s,%s,clock_timestamp(),%s)""", (doc_id, doc_id, PARSER_VERSION, outcome, message))

    def _set_version(self, doc_id: int, version: str) -> None:
        self.database.execute("UPDATE cbcr_staging.xml_document SET xml_schema_version=%s WHERE xml_document_id=%s", (version, doc_id))

    def _finish(self, doc_id: int, status: str, issues: Iterable[tuple]) -> None:
        with self.database.transaction() as db:
            db.execute("UPDATE cbcr_staging.xml_document SET parse_status=%s,parser_version=%s,parsed_at=clock_timestamp() WHERE xml_document_id=%s", (status, PARSER_VERSION, doc_id))
            db.execute("DELETE FROM cbcr_staging.xml_validation_issue WHERE xml_document_id=%s", (doc_id,))
            for severity, code, xpath, line, column, message in issues:
                db.execute("INSERT INTO cbcr_staging.xml_validation_issue(xml_document_id,severity,issue_code,xpath,line_number,column_number,message) VALUES(%s,%s,%s,%s,%s,%s,%s)", (doc_id,severity,code,xpath,line,column,message))
            self._attempt(db, doc_id, status, issues[0][5] if issues else status)

    def _map(self, root: etree._Element, doc_id: int, db: PostgreSQLSession) -> int:
        msg = child(root, "MessageSpec")
        if msg is None: raise ValueError("MessageSpec missing after validation")
        row = db.one("""INSERT INTO public.cbcr_message_spec(sending_entity_in,transmitting_country,receiving_country_list,message_type,language,message_ref_id,message_type_indic,reporting_period,timestamp,xml_document_id,warning,contact)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING message_spec_id""", (text(msg,"SendingEntityIN"),text(msg,"TransmittingCountry"),",".join(filter(None,[text(x) for x in children(msg,"ReceivingCountry")])),text(msg,"MessageType"),text(msg,"Language"),text(msg,"MessageRefId"),text(msg,"MessageTypeIndic"),text(msg,"ReportingPeriod"),text(msg,"Timestamp"),doc_id,text(msg,"Warning"),text(msg,"Contact")))
        mid=row["message_spec_id"]
        for i,x in enumerate(children(msg,"ReceivingCountry"),1): db.execute("INSERT INTO public.cbcr_message_receiving_country VALUES(%s,%s,%s)",(mid,i,text(x)))
        for i,x in enumerate(children(msg,"CorrMessageRefId"),1): db.execute("INSERT INTO public.cbcr_message_correction_ref VALUES(%s,%s,%s)",(mid,i,text(x)))
        for ordinal, body in enumerate(children(root,"CbcBody"),1): self._body(body,mid,ordinal,db)
        return mid

    def _body(self, body, mid, ordinal, db):
        bid=db.one("INSERT INTO public.cbcr_body(message_spec_id,body_ordinal) VALUES(%s,%s) RETURNING cbc_body_id",(mid,ordinal))["cbc_body_id"]
        rep=child(body,"ReportingEntity")
        if rep is not None: self._reporting_entity(rep,mid,bid,db)
        for report in children(body,"CbcReports"): self._cbc_report(report,mid,bid,db)
        for info in children(body,"AdditionalInfo"): self._additional_info(info,mid,bid,db)

    def _reporting_entity(self, e, mid, bid, db):
        doc=child(e,"DocSpec"); period=child(e,"ReportingPeriod")
        rid=db.one("""INSERT INTO public.cbcr_reporting_entity(message_spec_id,name_mne_group,reporting_role,reporting_period_start,reporting_period_end,doc_type_indic,doc_ref_id,cbc_body_id)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING reporting_entity_id""",(mid,text(e,"NameMNEGroup"),text(e,"ReportingRole"),text(period,"StartDate"),text(period,"EndDate"),text(doc,"DocTypeIndic"),text(doc,"DocRefId"),bid))["reporting_entity_id"]
        self._party(child(e,"Entity"),"reporting_entity",rid,db); self._doc_corrections(doc,"reporting_entity",rid,db)

    def _party(self, party, kind, owner, db):
        if party is None:return
        fk="reporting_entity_id" if kind=="reporting_entity" else "const_entity_id"
        for i,x in enumerate(children(party,"ResCountryCode"),1): db.execute(f"INSERT INTO public.cbcr_organisation_residence(organisation_type,{fk},residence_ordinal,country_code) VALUES(%s,%s,%s,%s)",(kind,owner,i,text(x)))
        for i,x in enumerate(children(party,"Name"),1): db.execute(f"INSERT INTO public.cbcr_organisation_name(organisation_type,{fk},name_ordinal,organisation_name) VALUES(%s,%s,%s,%s)",(kind,owner,i,text(x)))
        for i,x in enumerate(children(party,"IN"),1): db.execute(f"INSERT INTO public.cbcr_organisation_identifier(organisation_type,{fk},identifier_ordinal,identifier_value,issued_by,identifier_type) VALUES(%s,%s,%s,%s,%s,%s)",(kind,owner,i,text(x),x.get("issuedBy"),x.get("INType")))
        table = "cbcr_entity_address" if kind == "reporting_entity" else "cbcr_const_entity_address"
        key = "reporting_entity_id" if kind == "reporting_entity" else "const_entity_id"
        for i, address in enumerate(children(party, "Address"), 1):
            fixed = child(address, "AddressFix")
            db.execute(f"""INSERT INTO public.{table}({key},country_code,address_free,address_ordinal,legal_address_type,street,building_identifier,suite_identifier,floor_identifier,district_name,pob,post_code,city,country_subentity)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (owner,text(address,"CountryCode"),text(address,"AddressFree"),i,address.get("legalAddressType"),text(fixed,"Street"),text(fixed,"BuildingIdentifier"),text(fixed,"SuiteIdentifier"),text(fixed,"FloorIdentifier"),text(fixed,"DistrictName"),text(fixed,"POB"),text(fixed,"PostCode"),text(fixed,"City"),text(fixed,"CountrySubentity")))

    def _cbc_report(self,e,mid,bid,db):
        doc=child(e,"DocSpec"); cid=db.one("INSERT INTO public.cbcr_cbcreport(message_spec_id,res_country_code,doc_type_indic,doc_ref_id,cbc_body_id) VALUES(%s,%s,%s,%s,%s) RETURNING cbcreport_id",(mid,text(e,"ResCountryCode"),text(doc,"DocTypeIndic"),text(doc,"DocRefId"),bid))["cbcreport_id"]
        s=child(e,"Summary"); rev=child(s,"Revenues")
        vals=[decimal(child(rev,n)) for n in ("Unrelated","Related","Total")]+[decimal(child(s,n)) for n in ("ProfitOrLoss","TaxPaid","TaxAccrued","Capital","Earnings")]+[text(s,"NbEmployees"),decimal(child(s,"Assets"))]
        cur=[child(rev,n).get("currCode") if child(rev,n) is not None else None for n in ("Unrelated","Related","Total")]+[child(s,n).get("currCode") if child(s,n) is not None else None for n in ("ProfitOrLoss","TaxPaid","TaxAccrued","Capital","Earnings","Assets")]
        db.execute("""INSERT INTO public.cbcr_cbcreport_summary(cbcreport_id,revenue_unrelated,revenue_related,revenue_total,profit_or_loss,tax_paid,tax_accrued,capital,earnings,nb_employees,assets,revenue_unrelated_currency,revenue_related_currency,revenue_total_currency,profit_or_loss_currency,tax_paid_currency,tax_accrued_currency,capital_currency,earnings_currency,assets_currency)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(cid,*vals,*cur))
        self._doc_corrections(doc,"cbc_report",cid,db)
        for group in children(e,"ConstEntities"): self._constituent(group,cid,db)

    def _constituent(self,g,cid,db):
        party=child(g,"ConstEntity"); ce=db.one("INSERT INTO public.cbcr_const_entity(cbcreport_id,res_country_code,tin,tin_issued_by,in_number,name,incorp_country_code,role,biz_activities,other_entity_info) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING const_entity_id",(cid,text(party,"ResCountryCode"),text(party,"TIN"),child(party,"TIN").get("issuedBy") if child(party,"TIN") is not None else None,text(party,"IN"),text(party,"Name"),text(g,"IncorpCountryCode"),text(g,"Role"),None,text(g,"OtherEntityInfo")))["const_entity_id"]
        self._party(party,"constituent_entity",ce,db)
        for i,x in enumerate(children(g,"BizActivities"),1): db.execute("INSERT INTO public.cbcr_const_entity_business_activity VALUES(%s,%s,%s)",(ce,i,text(x)))

    def _additional_info(self,e,mid,bid,db):
        doc=child(e,"DocSpec"); aid=db.one("INSERT INTO public.cbcr_additional_info(message_spec_id,doc_type_indic,doc_ref_id,other_info,language,res_country_code,summary_ref,cbc_body_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING additional_info_id",(mid,text(doc,"DocTypeIndic"),text(doc,"DocRefId"),text(e,"OtherInfo"),child(e,"OtherInfo").get("language") if child(e,"OtherInfo") is not None else None,text(e,"ResCountryCode"),text(e,"SummaryRef"),bid))["additional_info_id"]
        for i,x in enumerate(children(e,"OtherInfo"),1):db.execute("INSERT INTO public.cbcr_additional_info_text VALUES(%s,%s,%s,%s)",(aid,i,text(x),x.get("language")))
        for i,x in enumerate(children(e,"ResCountryCode"),1):db.execute("INSERT INTO public.cbcr_additional_info_country VALUES(%s,%s,%s)",(aid,i,text(x)))
        for i,x in enumerate(children(e,"SummaryRef"),1):db.execute("INSERT INTO public.cbcr_additional_info_summary_ref VALUES(%s,%s,%s)",(aid,i,text(x)))
        self._doc_corrections(doc,"additional_info",aid,db)

    def _doc_corrections(self,doc,typ,owner,db):
        if doc is None:return
        col={"reporting_entity":"reporting_entity_id","cbc_report":"cbcreport_id","additional_info":"additional_info_id"}[typ]
        for i,x in enumerate(children(doc,"CorrDocRefId"),1): db.execute(f"INSERT INTO public.cbcr_document_correction_ref(document_type,{col},correction_ordinal,corr_doc_ref_id) VALUES(%s,%s,%s,%s)",(typ,owner,i,text(x)))
