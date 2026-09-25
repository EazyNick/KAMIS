from datetime import date
from types import SimpleNamespace

import pytest

from app.collectors import coupang, kamis, market, naver
from app.domain.models import RunStatus
from app.services.online_collection import OnlineCollectionResult


@pytest.mark.parametrize("module", [naver, coupang])
def test_shopping_entrypoint_accepts_date_target_and_headful(
    module, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = {}
    runner_name = f"run_{module.__name__.rsplit('.', 1)[-1]}"

    def run(observed_date, *, target, headful):
        captured.update(
            observed_date=observed_date,
            target=target,
            headful=headful,
        )
        return OnlineCollectionResult(1, 1, 0, ())

    monkeypatch.setattr(module, runner_name, run)
    monkeypatch.setattr(
        module.Settings,
        "from_env",
        staticmethod(lambda: SimpleNamespace(timezone="Asia/Seoul")),
    )

    exit_code = module.main(["--date", "2026-09-25", "--item", "111:10", "--headful"])

    assert exit_code == 0
    assert captured == {
        "observed_date": date(2026, 9, 25),
        "target": ("111", "10"),
        "headful": True,
    }


@pytest.mark.parametrize(
    ("module", "runner_name"),
    [(kamis, "run_kamis"), (market, "run_market")],
)
def test_non_shopping_entrypoint_accepts_date(
    module, runner_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = []

    def run(observed_date):
        captured.append(observed_date)
        return SimpleNamespace(status=RunStatus.SUCCESS)

    monkeypatch.setattr(module, runner_name, run)
    monkeypatch.setattr(
        module.Settings,
        "from_env",
        staticmethod(lambda: SimpleNamespace(timezone="Asia/Seoul")),
    )

    assert module.main(["--date", "2026-09-25"]) == 0
    assert captured == [date(2026, 9, 25)]
