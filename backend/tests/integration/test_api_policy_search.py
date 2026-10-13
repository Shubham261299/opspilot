"""Policy search and rule citations, with the fake hashing embedder (words that two texts share
make them close), against real Postgres + pgvector."""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.llm.client import LlmError
from tests.integration.conftest import HashingEmbedder
from tests.integration.test_api import upload_form
from tests.integration.test_api_policy import upload as upload_policy


@pytest.fixture
async def with_policy(client: AsyncClient, sample_data_dir: Path) -> AsyncClient:
    response = await upload_policy(client, (sample_data_dir / "company_policy.pdf").read_bytes())
    assert response.status_code == 201
    return client


async def test_the_whole_policy_is_listed_in_order(with_policy: AsyncClient) -> None:
    body = (await with_policy.get("/policy")).json()
    assert [r["code"] for r in body["items"]][:6] == ["1.1", "1.2", "1.3", "1.4", "1.5", "2.1"]
    assert len(body["items"]) == 15
    assert body["embedding_model"] == "fake-hashing-embedder"
    assert body["uploaded_at"] is not None


async def test_before_any_upload_the_policy_is_empty_and_search_has_nothing_to_search(
    client: AsyncClient,
) -> None:
    assert (await client.get("/policy")).json() == {
        "items": [],
        "embedding_model": None,
        "uploaded_at": None,
    }
    found = (await client.get("/policy/search", params={"q": "when to put orders on hold"})).json()
    assert (found["items"], found["embedding_model"]) == ([], None)


async def test_search_returns_the_closest_rules_first_with_their_scores(
    with_policy: AsyncClient, embedder: HashingEmbedder
) -> None:
    response = await with_policy.get(
        "/policy/search", params={"q": "put new orders on hold when a bill is overdue", "limit": 3}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["code"] for i in items][0] == "2.4"
    assert len(items) == 3
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True) and 0 < scores[-1] < scores[0] <= 1
    assert items[0]["section_title"] == "Customer credit"
    assert items[0]["text"].startswith("Put new orders ON HOLD")
    assert embedder.calls[-1][1] == "query"  # the question is embedded as a query


async def test_search_refuses_rules_embedded_by_another_model(
    with_policy: AsyncClient, embedder: HashingEmbedder
) -> None:
    embedder.model = "another-model"  # the configured model changed after the upload
    response = await with_policy.get("/policy/search", params={"q": "credit limit"})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "policy_needs_reembedding"
    assert "fake-hashing-embedder" in error["message"] and "another-model" in error["message"]


async def test_search_reports_an_unreachable_embedding_model(with_policy: AsyncClient) -> None:
    from app.api.deps import get_embedder
    from app.main import app

    async def broken(texts: list[str], kind: str = "document") -> Any:
        raise LlmError("unavailable", "The embedding model (x) could not be reached.")

    app.dependency_overrides[get_embedder] = lambda: broken
    response = await with_policy.get("/policy/search", params={"q": "credit limit"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "embedding_unavailable"


async def test_a_question_that_is_too_short_is_refused(with_policy: AsyncClient) -> None:
    assert (await with_policy.get("/policy/search", params={"q": "ab"})).status_code == 422


# Citations on proposals -----------------------------------------------------------------


async def load_sample_files(client: AsyncClient, sample_data_dir: Path) -> None:
    for path, name in [
        ("/uploads/stock", "stock_register.xlsx"),
        ("/uploads/customers", "customers.xlsx"),
        ("/uploads/dues", "outstanding_dues.xlsx"),
        ("/uploads/sales", "sales_history_90d.csv"),
    ]:
        response = await client.post(
            path, files=upload_form(name, (sample_data_dir / name).read_bytes())
        )
        assert response.status_code == 201, response.text


@pytest.mark.usefixtures("seeded")
async def test_proposals_cite_their_rules_with_the_stored_wording(
    client: AsyncClient, sample_data_dir: Path
) -> None:
    from datetime import date

    from app.api.deps import get_today
    from app.main import app

    app.dependency_overrides[get_today] = lambda: date(2026, 9, 24)
    await load_sample_files(client, sample_data_dir)
    await upload_policy(client, (sample_data_dir / "company_policy.pdf").read_bytes())
    assert (await client.post("/proposals/run")).status_code == 200

    items = (await client.get("/proposals")).json()["items"]
    reorder = next(p for p in items if p["kind"] == "reorder")
    hold = next(p for p in items if p["kind"] == "hold_orders")
    reminder = next(p for p in items if p["kind"] == "payment_reminder")

    assert [c["code"] for c in reorder["policy"]][:3] == ["1.2", "1.3", "1.4"]
    assert reorder["policy"][0]["text"].startswith("Reorder point = average daily sales")
    assert reorder["policy"][0]["section_title"] == "Stock and reordering"
    [rule_2_4] = hold["policy"]
    assert rule_2_4["code"] == "2.4" and "days overdue" in rule_2_4["why"]
    assert rule_2_4["text"].startswith("Put new orders ON HOLD")
    assert [c["code"] for c in reminder["policy"]] == ["2.3", "2.5"]


@pytest.mark.usefixtures("seeded")
async def test_citations_still_name_the_rule_before_the_policy_is_uploaded(
    client: AsyncClient, sample_data_dir: Path
) -> None:
    from datetime import date

    from app.api.deps import get_today
    from app.main import app

    app.dependency_overrides[get_today] = lambda: date(2026, 9, 24)
    await load_sample_files(client, sample_data_dir)
    await client.post("/proposals/run")

    hold = next(
        p for p in (await client.get("/proposals")).json()["items"] if p["kind"] == "hold_orders"
    )
    [cited] = hold["policy"]
    assert (cited["code"], cited["text"], cited["section_title"]) == ("2.4", None, None)
    assert cited["why"]  # the reason comes from code, not from the stored policy
