"""Security report generation (PDF via ReportLab).

The report is assembled exclusively from stored, measured data: the analysis record,
its explanation/forensic summary, attack experiments on the same file hash, any
embedding operation that produced the file, and the model registry entry.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.core.permissions import Permission, has_permission
from app.db.models import AnalysisRecord, AttackExperiment, ModelVersion, Report, StegoOperation, User
from app.services import audit, storage
from app.services.audit import AuditAction

INK = colors.HexColor("#14161A")
MUTED = colors.HexColor("#6B6760")
LINE = colors.HexColor("#D9D5CE")
ACCENT = colors.HexColor("#0E7C82")  # print-safe teal counterpart of the UI scan-cyan
LEVEL_COLOURS = {"LOW": "#2E9E62", "MEDIUM": "#C98A12", "HIGH": "#D9363E", "CRITICAL": "#A3122A"}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=INK, alignment=TA_LEFT, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Helvetica", fontSize=8.5, textColor=MUTED, leading=11),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, textColor=INK, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=8.8, leading=12, textColor=INK),
        "small": ParagraphStyle("small", parent=base["Normal"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED),
        "mono": ParagraphStyle("mono", parent=base["Normal"], fontName="Courier", fontSize=7.6, leading=10, textColor=INK),
        "verdict": ParagraphStyle("verdict", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK),
    }


def _table(rows: list[list[Any]], widths: list[float], header: bool = True) -> Table:
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED), ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK)]
    table.setStyle(TableStyle(style))
    return table


def _pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 2, unit: str = "") -> str:
    return "—" if value is None else f"{value:.{digits}f}{unit}"


def _footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "StegoLab · AI-Enhanced Secure Steganography & Steganalysis · CONFIDENTIAL")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(2)
    canvas.line(18 * mm, A4[1] - 12 * mm, 40 * mm, A4[1] - 12 * mm)
    canvas.restoreState()


def _image_from_artifact(db: Session, artifact_id: str | None, user: User, width: float) -> RLImage | None:
    if not artifact_id:
        return None
    try:
        artifact = storage.get_owned_artifact(db, uuid.UUID(artifact_id), user)
        data = storage.read_artifact_bytes(artifact)
    except Exception:  # noqa: BLE001 - expired artifacts are simply omitted
        return None
    img = RLImage(io.BytesIO(data))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth, img.drawHeight = width, width * ratio
    return img


def build_pdf(db: Session, record: AnalysisRecord, user: User, report_id: uuid.UUID) -> tuple[bytes, dict[str, Any]]:
    st = _styles()
    story: list[Any] = []
    now = datetime.now(timezone.utc)
    details = record.details or {}
    risk = record.risk_factors or {}
    level = record.risk_level

    story.append(Paragraph("Steganalysis Security Report", st["title"]))
    story.append(Paragraph(
        f"Report {report_id} · generated {now.strftime('%Y-%m-%d %H:%M:%S UTC')} · analyst {user.name} &lt;{user.email}&gt; · "
        f"analysis {record.id} ({record.source}, {record.created_at.strftime('%Y-%m-%d %H:%M UTC')})", st["subtitle"]))  # fmt: skip
    story.append(Spacer(1, 8))

    # --- Executive summary
    verdict_colour = LEVEL_COLOURS.get(level, "#14161A")
    summary_rows = [
        [Paragraph(f"<font color='{verdict_colour}'>{record.prediction.upper()} · RISK {record.risk_score:.1f} / 100 · {level}</font>", st["verdict"])],
        [Paragraph(risk.get("recommendation", ""), st["body"])],
    ]
    summary = Table(summary_rows, colWidths=[174 * mm])
    summary.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(verdict_colour)), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.append(summary)

    # --- File information
    story.append(Paragraph("1. File information", st["h2"]))
    story.append(_table([
        ["Field", "Value"],
        ["File name", record.filename or "—"],
        ["Format", record.image_format.upper()],
        ["Dimensions", f"{record.width} × {record.height} px ({record.width * record.height / 1e6:.2f} MP)"],
        ["File size", f"{record.file_size:,} bytes"],
        ["SHA-256", Paragraph(record.file_hash, st["mono"])],
    ], [40 * mm, 134 * mm]))  # fmt: skip

    # --- AI classification
    story.append(Paragraph("2. AI classification", st["h2"]))
    rf = record.rf_probabilities or {}
    rows = [["Class", "StegoNet (CNN)", "Random Forest"]]
    for cls in ("normal", "lsb", "dct", "dwt"):
        rows.append([cls.upper(), _pct(record.probabilities.get(cls)), _pct(rf.get(cls)) if rf else "—"])
    story.append(_table(rows, [40 * mm, 67 * mm, 67 * mm]))
    model = db.scalar(select(ModelVersion).where(ModelVersion.model_name == record.model_name, ModelVersion.version == record.model_version))
    story.append(Spacer(1, 4))
    story.append(_table([
        ["Item", "Value"],
        ["Prediction / confidence", f"{record.prediction.upper()} · {_pct(record.confidence)}"],
        ["Predicted technique", f"{record.predicted_technique.upper()}" + (f" (P(technique | stego) = {_pct(details.get('technique_confidence'))})" if details.get("technique_confidence") else "")],
        ["Anomaly percentile", _pct(record.anomaly_score)],
        ["Model", f"{record.model_name} v{record.model_version}" + (f" · test accuracy {_pct(model.accuracy)} · macro-F1 {_num(model.f1, 3)}" if model else "")],
        ["Model weights SHA-256", Paragraph(model.weights_sha256 or "—", st["mono"]) if model else "—"],
        ["Tiles analysed / inference time", f"{record.tiles} · {record.inference_ms:.0f} ms"],
    ], [50 * mm, 124 * mm]))  # fmt: skip

    # --- Risk methodology
    story.append(Paragraph("3. Risk score derivation", st["h2"]))
    factor_rows = [["Factor", "Measured value", "Weight", "Contribution"]]
    for f in risk.get("factors", []):
        value = f.get("value")
        shown = _pct(value) if isinstance(value, (int, float)) else (str(value).upper() if value else "none")
        factor_rows.append([f["label"], shown, "—" if f.get("weight") is None else f"{f['weight']:.2f}", f"{f.get('contribution', 0):.1f}"])
    story.append(_table(factor_rows, [70 * mm, 40 * mm, 24 * mm, 40 * mm]))
    # Built-in PDF fonts lack Unicode subscripts, so the formula is spelled out in ASCII here.
    story.append(Paragraph("Formula: risk = 100 &#183; max(sum(w_i &#183; x_i) / sum(w_i), payload floor). The payload floor applies only when a StegoLab frame is physically present. Thresholds are administrator-configured.", st["small"]))

    # --- Explainability
    explanation = details.get("explanation")
    if explanation:
        block: list[Any] = [Paragraph("4. Explainable AI (Grad-CAM)", st["h2"])]
        overlay = _image_from_artifact(db, (record.artifacts or {}).get("overlay"), user, 80 * mm)
        share = explanation.get("branch_share", {})
        text = Paragraph(
            f"{explanation.get('note', '')}<br/><br/>Evidence share by analysis domain: spatial residuals {_pct(share.get('spatial'))}, "
            f"block-DCT {_pct(share.get('dct'))}, wavelet {_pct(share.get('dwt'))}.", st["body"])  # fmt: skip
        block.append(Table([[overlay or Paragraph("(heat-map artefact expired)", st["small"]), text]], colWidths=[86 * mm, 88 * mm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(KeepTogether(block))

    top = details.get("rf_top_features") or []
    if top:
        story.append(Paragraph("5. Most influential handcrafted features", st["h2"]))
        story.append(_table([["Feature", "Importance", "Value", "z vs clean covers"]] + [[t["feature"], f"{t['importance']:.3f}", f"{t['value']:.4g}", f"{t['z_vs_covers']:+.2f}"] for t in top], [70 * mm, 30 * mm, 34 * mm, 40 * mm]))

    findings = details.get("findings") or []
    if findings:
        story.append(Paragraph("6. Forensic findings", st["h2"]))
        story.append(_table([["Severity", "Finding", "Detail"]] + [[f["severity"].upper(), Paragraph(f["title"], st["body"]), Paragraph(f["detail"], st["small"])] for f in findings], [20 * mm, 50 * mm, 104 * mm]))
        story.append(Paragraph("Metadata and individual statistics can be explained by ordinary processing; none alone proves hidden data.", st["small"]))

    attacks = db.scalars(
        select(AttackExperiment).where(AttackExperiment.source_image == record.file_hash, AttackExperiment.user_id == record.user_id).order_by(AttackExperiment.created_at.desc()).limit(25)
    ).all()
    if attacks:
        story.append(Paragraph("7. Attack / robustness results (same file hash)", st["h2"]))
        rows = [["Attack", "Parameters", "P(stego)", "Extraction", "Integrity", "PSNR"]]
        for a in attacks:
            params = ", ".join(f"{k}={v:g}" for k, v in (a.attack_parameters or {}).items())
            rows.append([a.attack_type, params, _pct(a.detection_probability), "SUCCESS" if a.extraction_success else "FAILED", a.integrity_status.upper(), _num(a.psnr, 2, " dB")])
        story.append(_table(rows, [30 * mm, 42 * mm, 24 * mm, 26 * mm, 26 * mm, 26 * mm]))

    op = db.scalar(select(StegoOperation).where(StegoOperation.stego_hash == record.file_hash, StegoOperation.operation == "embed").order_by(StegoOperation.created_at.desc()))
    if op:
        story.append(Paragraph("8. Embedding provenance (this file was produced by StegoLab)", st["h2"]))
        story.append(_table([
            ["Algorithm", "Payload", "Utilisation", "PSNR", "SSIM", "MSE"],
            [op.algorithm.upper(), f"{op.payload_size:,} B", _pct(op.utilization), _num(op.psnr, 2, " dB"), _num(op.ssim, 4), _num(op.mse, 4)],
        ], [29 * mm] * 6))  # fmt: skip

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Interpretation notes: probabilities are model outputs on 256×256 tiles averaged over the image; low embedding rates are "
        "substantially harder to detect (see model evaluation by utilisation). Grad-CAM shows where evidence was found, not the exact "
        "pixels carrying data.", st["small"]))  # fmt: skip

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="StegoLab Security Report", author="StegoLab", subject=f"Analysis {record.id}")  # fmt: skip
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    summary_data = {
        "prediction": record.prediction,
        "risk_score": record.risk_score,
        "risk_level": record.risk_level,
        "technique": record.predicted_technique,
        "model_version": record.model_version,
        "attacks_included": len(attacks),
        "findings_included": len(findings),
        "filename": record.filename,
    }
    return buf.getvalue(), summary_data


def generate(db: Session, user: User, analysis_id: uuid.UUID, ip: str | None) -> Report:
    record = db.get(AnalysisRecord, analysis_id)
    if record is None or (record.user_id != user.id and not has_permission(user.role, Permission.HISTORY_ALL)):
        raise NotFound("Analysis not found")
    report_id = uuid.uuid4()
    pdf, summary = build_pdf(db, record, user, report_id)
    artifact = storage.save_artifact(db, user=user, kind="report", data=pdf, mime="application/pdf", temporary=False)
    report = Report(
        id=report_id,
        user_id=user.id,
        analysis_id=record.id,
        title=f"Security report · {record.filename or record.file_hash[:12]}",
        artifact_id=artifact.id,
        sha256=hashlib.sha256(pdf).hexdigest(),
        summary=summary,
    )
    db.add(report)
    audit.record(db, AuditAction.REPORT_GENERATED, "success", user=user, ip=ip, commit=False, report_id=str(report_id), analysis_id=str(record.id), report_hash=report.sha256)
    db.commit()
    return report
