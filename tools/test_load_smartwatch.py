import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_smartwatch as ls  # noqa: E402

HEAD = ",".join(ls.HEADER)


def row(**kw):
    base = dict.fromkeys(ls.HEADER, "")
    base.update(dataset="actual", period="2026Q2", country="US", vendor="Apple", sell_in_mu="1.5",
                published_month="2026-07-01")
    base.update(kw)
    return base


def csv_line(r):
    return ",".join(r[c] for c in ls.HEADER)


def write_csv(path, rows, bom=False, header=HEAD):
    path.write_text(header + "\n" + "\n".join(csv_line(r) for r in rows) + "\n",
                    encoding="utf-8-sig" if bom else "utf-8")
    return path


# ---------- validation ----------

def test_good_row_per_dataset_and_firm_defaults():
    r, e = ls.validate_row(row())
    assert e == [] and r["firm"] == "TechInsights" and r["sell_in_mu"] == Decimal("1.5") and r["note"] is None
    r, e = ls.validate_row(row(dataset="our_tam", country="Worldwide", firm=""))
    assert e == [] and r["firm"] == "MI"
    r, e = ls.validate_row(row(dataset="forecast", period="2027", sell_in_mu="", revenue_musd="1000", asp_usd="250"))
    assert e == [] and r["sell_in_mu"] == Decimal("4.000") and r["firm"] == "TechInsights"


@pytest.mark.parametrize("kw,word", [
    ({"dataset": "bogus"}, "dataset"),
    ({"period": "2026"}, "period"),
    ({"period": "2026Q5"}, "period"),
    ({"dataset": "forecast", "period": "2026Q1", "revenue_musd": "10", "asp_usd": "5", "sell_in_mu": ""}, "period"),
    ({"country": ""}, "country"),
    ({"dataset": "our_tam", "country": "US"}, "Worldwide"),
    ({"vendor": "Sony"}, "vendor"),
    ({"sell_in_mu": ""}, "sell_in_mu"),
    ({"sell_in_mu": "-1"}, "sell_in_mu"),
    ({"sell_in_mu": "abc"}, "sell_in_mu"),
    ({"revenue_musd": "5"}, "revenue_musd"),
    ({"asp_usd": "5"}, "revenue_musd"),
    ({"published_month": "2026-07-15"}, "1일"),
    ({"published_month": "July"}, "ISO"),
    ({"dataset": "forecast", "period": "2027", "sell_in_mu": "", "revenue_musd": "", "asp_usd": "5"}, "revenue_musd"),
    ({"dataset": "forecast", "period": "2027", "sell_in_mu": "", "revenue_musd": "10", "asp_usd": "0"}, "asp_usd"),
    ({"dataset": "forecast", "period": "2027", "sell_in_mu": "", "revenue_musd": "-3", "asp_usd": "5"}, "revenue_musd"),
])
def test_validation_failures(kw, word):
    r, e = ls.validate_row(row(**kw))
    assert r is None and any(word in m for m in e)


def test_forecast_one_percent_rule():
    f = dict(dataset="forecast", period="2027", revenue_musd="1000", asp_usd="250")
    r, e = ls.validate_row(row(sell_in_mu="4.03", **f))  # within 1% of 4.000
    assert e == [] and r["sell_in_mu"] == Decimal("4.03")
    r, e = ls.validate_row(row(sell_in_mu="4.05", **f))
    assert r is None and "1%" in e[0]


def test_duplicate_key_in_file_and_all_errors_collected(tmp_path):
    p = write_csv(tmp_path / "a.csv", [row(), row(sell_in_mu="2"), row(vendor="Sony"), row(dataset="x")])
    rows, errs = ls.read_csv(p)
    assert len(rows) == 1 and len(errs) == 3
    assert any("a.csv 행 3" in e and "중복" in e for e in errs)
    assert any("행 4" in e for e in errs) and any("행 5" in e for e in errs)


def test_bom_header_and_bad_header_and_extra_columns(tmp_path):
    rows, errs = ls.read_csv(write_csv(tmp_path / "bom.csv", [row()], bom=True))
    assert errs == [] and len(rows) == 1
    _, errs = ls.read_csv(write_csv(tmp_path / "h.csv", [row()], header=HEAD + ",extra"))
    assert errs and "헤더" in errs[0]
    p = tmp_path / "cols.csv"
    p.write_text(HEAD + "\n" + csv_line(row()) + ",oops\n", encoding="utf-8")
    assert "열 수" in ls.read_csv(p)[1][0]


def test_whitespace_trimmed_and_note_kept(tmp_path):
    p = write_csv(tmp_path / "w.csv", [row(vendor=" Apple ", note=" 메모 ")])
    rows, errs = ls.read_csv(p)
    assert errs == [] and rows[0]["vendor"] == "Apple" and rows[0]["note"] == "메모"


def test_check_prints_summary_and_fails_without_writing(tmp_path, capsys):
    good = write_csv(tmp_path / "g.csv", [row(), row(vendor="Samsung")])
    assert ls.main(["check", str(good)]) == 0
    assert "| actual | 2026Q2 | 2026-07-01 | 2 |" in capsys.readouterr().out
    bad = write_csv(tmp_path / "b.csv", [row(vendor="Sony")])
    assert ls.main(["check", str(good), str(bad)]) == 1
    assert "b.csv 행 2" in capsys.readouterr().err
    assert ls.main(["check", str(tmp_path / "missing.csv")]) == 1


def test_setup_errors_exit_2(tmp_path, monkeypatch, capsys):
    f = write_csv(tmp_path / "g.csv", [row()])
    monkeypatch.delenv("MI_DB_REPORTS_WRITE", raising=False)
    assert ls.main(["load", "--dsn-env", "MI_DB_REPORTS_WRITE", str(f)]) == 2
    assert ls.main(["load", "--dsn-env", "postgresql://u:TOPSECRET@h/db", str(f)]) == 2
    assert "TOPSECRET" not in capsys.readouterr().err
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", "postgresql://writer:Pa@ssW0rd@127.0.0.1:1/db")
    assert ls.main(["load", "--dsn-env", "MI_DB_REPORTS_WRITE", str(f)]) == 2
    assert ls.main(["latest", "--dsn-env", "NOPE_NOT_SET"]) == 2


# ---------- pgserver integration ----------

def query(staging, sql):
    pgserver = pytest.importorskip("pgserver")
    import psycopg

    with pgserver.get_server(staging / "localpg") as s, psycopg.connect(s.get_uri()) as c:
        return c.execute(sql).fetchall()


def test_load_local_twice_skips_and_latest_picks_greater_month(tmp_path, capsys):
    pytest.importorskip("pgserver")
    st = tmp_path / "staging"
    old = write_csv(tmp_path / "old.csv", [row(sell_in_mu="1.5", published_month="2026-07-01")])
    new = write_csv(tmp_path / "new.csv", [row(sell_in_mu="1.7", published_month="2026-10-01"),
                                           row(dataset="forecast", period="2027", country="US", vendor="Apple",
                                               sell_in_mu="", revenue_musd="1000", asp_usd="250",
                                               published_month="2026-10-01")])
    argv = ["--staging", str(st), "load", "--local", str(old), str(new)]
    assert ls.main(argv) == 0
    assert "적재 3, 건너뜀 0, 실패 0" in capsys.readouterr().out
    assert ls.main(argv) == 0
    assert "적재 0, 건너뜀 3, 실패 0" in capsys.readouterr().out

    assert ls.main(["--staging", str(st), "latest", "--local", "--dataset", "actual"]) == 0
    out = capsys.readouterr().out
    assert "2026-10-01" in out and "2026-07-01" not in out and "forecast" not in out and "(총 1 행)" in out

    rows = query(st, f"SELECT sell_in_mu, revenue_musd, asp_usd FROM {ls.TABLE} WHERE dataset = 'forecast'")
    assert rows == [(Decimal("4.000"), Decimal("1000.000"), Decimal("250.00"))]
    assert query(st, f"SELECT count(*) FROM {ls.TABLE}") == [(3,)]


def test_invalid_file_writes_nothing(tmp_path, capsys):
    pytest.importorskip("pgserver")
    st = tmp_path / "staging"
    good = write_csv(tmp_path / "g.csv", [row()])
    bad = write_csv(tmp_path / "b.csv", [row(vendor="Sony")])
    assert ls.main(["--staging", str(st), "load", "--local", str(good), str(bad)]) == 1
    assert not (st / "localpg").exists()


def test_latest_truncates_at_200_rows(tmp_path, capsys, monkeypatch):
    pytest.importorskip("pgserver")
    st = tmp_path / "staging"
    f = write_csv(tmp_path / "many.csv", [row(period=f"{2000 + i // 4}Q{i % 4 + 1}") for i in range(203)])
    assert ls.main(["--staging", str(st), "load", "--local", str(f)]) == 0
    capsys.readouterr()
    assert ls.main(["--staging", str(st), "latest", "--local"]) == 0
    assert "(총 203 행, 3 행 생략)" in capsys.readouterr().out


def test_load_redacts_secret_inside_driver_exception(tmp_path, monkeypatch, capsys):
    import psycopg

    def boom(*a, **k):
        raise psycopg.OperationalError("connection failed: password=ZZsecretZZ host=x")

    monkeypatch.setattr(psycopg, "connect", boom)
    monkeypatch.setenv("MI_DB_REPORTS_WRITE", "postgresql://writer:ZZsecretZZ@127.0.0.1:1/db")
    f = write_csv(tmp_path / "g.csv", [row()])
    assert ls.main(["load", "--dsn-env", "MI_DB_REPORTS_WRITE", str(f)]) == 1
    cap = capsys.readouterr()
    assert "ZZsecretZZ" not in cap.out + cap.err and "[load_smartwatch]" in cap.err


def test_company_mode_refuses_missing_table_and_creates_nothing(tmp_path, monkeypatch, capsys):
    pgserver = pytest.importorskip("pgserver")
    import psycopg

    f = write_csv(tmp_path / "g.csv", [row()])
    with pgserver.get_server(tmp_path / "pg") as s:
        monkeypatch.setenv("MI_DB_REPORTS_WRITE", s.get_uri())
        assert ls.main(["load", "--dsn-env", "MI_DB_REPORTS_WRITE", str(f)]) == 1
        assert "DBaaS" in capsys.readouterr().err
        with psycopg.connect(s.get_uri()) as c:
            assert c.execute("SELECT to_regnamespace('sales_team')").fetchone()[0] is None
