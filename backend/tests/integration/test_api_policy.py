"""The company policy upload end to end, with a fake embedding model: PDF -> numbered rules with
vectors in Postgres (pgvector), replaced as a whole on every upload."""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, PolicyRule, Upload
from app.llm.client import LlmError
from tests.integration.conftest import HashingEmbedder


@pytest.fixture
def policy_pdf(sample_data_dir: Path) -> bytes:
    return (sample_data_dir / "company_policy.pdf").read_bytes()


async def upload(client: AsyncClient, content: bytes, name: str = "company_policy.pdf") -> Any:
    return await client.post("/uploads/policy", files={"file": (name, content, "application/pdf")})


async def test_the_policy_is_read_embedded_and_saved(
    client: AsyncClient, db_session: AsyncSession, policy_pdf: bytes, embedder: HashingEmbedder
) -> None:
    response = await upload(client, policy_pdf)

    assert response.status_code == 201
    body = response.json()
    assert (body["rules_loaded"], body["embedding_model"]) == (15, "fake-hashing-embedder")
    assert (body["upload"]["kind"], body["upload"]["status"]) == ("company_policy", "processed")
    assert body["issues_by_severity"] == {"error": 0, "warning": 0, "info": 0}

    rules = (await db_session.scalars(select(PolicyRule).order_by(PolicyRule.id))).all()
    assert [r.code for r in rules][:5] == ["1.1", "1.2", "1.3", "1.4", "1.5"]
    hold = next(r for r in rules if r.code == "2.4")
    assert hold.section_title == "Customer credit"
    assert hold.text.startswith("Put new orders ON HOLD")
    assert len(hold.embedding) == 768
    assert hold.embedding_model == "fake-hashing-embedder"
    # One embedding call for all rules, each embedded with its section title, as documents.
    [(texts, kind)] = embedder.calls
    assert (len(texts), kind) == (15, "document")
    assert texts[8].startswith("Customer credit: Put new orders ON HOLD")


async def test_uploading_again_replaces_every_rule_and_keeps_the_history(
    client: AsyncClient, db_session: AsyncSession, policy_pdf: bytes
) -> None:
    first = (await upload(client, policy_pdf)).json()["upload"]["id"]
    second = (await upload(client, policy_pdf, "policy_v3_again.pdf")).json()["upload"]["id"]

    assert second != first  # the same file is accepted again: that is how rules are re-embedded
    assert await db_session.scalar(select(func.count()).select_from(PolicyRule)) == 15
    owners = set(await db_session.scalars(select(PolicyRule.upload_id)))
    assert owners == {second}
    audit = (
        await db_session.scalars(select(AuditLog).where(AuditLog.entity_id == str(second)).limit(1))
    ).one()
    assert audit.before == {"rules": 15, "embedding_model": "fake-hashing-embedder"}
    assert audit.after is not None and audit.after["embedding_model"] == "fake-hashing-embedder"
    assert len(audit.after["rules"]) == 15


async def test_a_failing_embedding_model_leaves_the_stored_policy_alone(
    client: AsyncClient, db_session: AsyncSession, policy_pdf: bytes
) -> None:
    from app.api.deps import get_embedder
    from app.main import app

    await upload(client, policy_pdf)

    async def broken(texts: list[str], kind: str = "document") -> Any:
        raise LlmError("unavailable", "The embedding model (x) could not be reached.")

    app.dependency_overrides[get_embedder] = lambda: broken
    response = await upload(client, policy_pdf)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "embedding_failed"
    assert "already stored was left as it was" in error["message"]
    assert await db_session.scalar(select(func.count()).select_from(PolicyRule)) == 15
    failed = await db_session.get(Upload, error["details"]["upload_id"])
    assert failed is not None and failed.status == "failed"


def _text_pdf(line: str) -> bytes:
    """The smallest valid PDF that has one line of text on its page."""
    stream = f"BT /F1 12 Tf 72 700 Td ({line}) Tj ET"
    objects = [
        "<</Type/Catalog/Pages 2 0 R>>",
        "<</Type/Pages/Kids[3 0 R]/Count 1>>",
        "<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R"
        "/Resources<</Font<</F1 5 0 R>>>>>>",
        f"<</Length {len(stream)}>>\nstream\n{stream}\nendstream",
        "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n"
    xref = len(out)  # the byte where the cross-reference table starts, which readers look for
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<</Root 1 0 R/Size {len(objects) + 1}>>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


async def test_a_pdf_without_numbered_rules_is_refused_and_recorded(client: AsyncClient) -> None:
    pdf = _text_pdf("A page of text that has no numbered rules in it at all.")
    response = await upload(client, pdf)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_rules"


async def test_only_pdfs_are_accepted(client: AsyncClient) -> None:
    response = await upload(client, b"1.1 A rule", "policy.txt")
    assert response.status_code == 415
