"""质检滞后统一按真实交易日历统计，兼容历史忽略台账。"""

import json
from datetime import date

import pytest

from backend.services.data_report import DataIntegrityReport


@pytest.fixture()
def calendar(market):
    market.execute("INSERT INTO trade_calendar VALUES ('2026-09-30',TRUE),"
                   "('2026-10-09',TRUE),('2026-10-12',TRUE),('2026-10-13',TRUE),"
                   "('2026-10-14',TRUE),('2026-10-15',TRUE),('2026-10-16',TRUE),"
                   "('2026-10-19',TRUE),('2026-10-20',TRUE)")
    return market


@pytest.mark.parametrize('start,end,expected', [
    ('2026-10-16', '2026-10-19', 1),
    ('2026-09-30', '2026-10-09', 1),
    ('2026-10-15', '2026-10-19', 2),
    ('2026-10-19', '2026-10-19', 0),
    ('2026-09-29', '2026-10-19', None),
    ('2026-10-19', '2026-10-21', None),
])
def test_lag_uses_open_dates_and_requires_calendar_coverage(calendar, start, end, expected):
    pair = date.fromisoformat(start), date.fromisoformat(end)
    assert DataIntegrityReport(calendar)._trading_day_lags([pair])[pair] == expected


def test_fund_scan_persists_trading_day_counts_for_all_periods(calendar):
    calendar.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('600000.SH','2026-10-19',10)")
    calendar.execute("INSERT INTO board_fund_flow(board_code,snapshot_date,period,net_inflow) "
                     "VALUES ('309121','2026-10-16','即时',1),('309121','2026-10-15','3日',1)")
    result = DataIntegrityReport(calendar).scan_board_quality()
    assert result['fund_stale'] == 1
    payload = json.loads(calendar.query_df(
        "SELECT detail FROM data_quality_issue WHERE issue_type='board_fund_stale'"
    ).iloc[0]['detail'])
    assert payload['lag_unit'] == 'trading_day'
    assert payload['lag_days'] == {'即时': 1, '3日': 2}
    assert '滞后 1 个交易日' in payload['message']
    assert '滞后 2 个交易日' in payload['message']
    assert '滞后 3 天' not in payload['message']


@pytest.mark.parametrize('kind', ['board', 'market'])
def test_index_lag_shares_trading_day_unit(calendar, kind):
    report = DataIntegrityReport(calendar)
    calendar.execute("INSERT INTO daily_bar(code,trade_date,close) VALUES ('600000.SH','2026-10-19',10)")
    if kind == 'board':
        calendar.execute("INSERT INTO board_dict(board_code,name,board_type,has_bar) "
                         "VALUES ('309121','AI PC','concept',TRUE)")
        calendar.execute("INSERT INTO board_bar(board_code,trade_date,close) VALUES ('309121','2026-10-16',10)")
        issues = report.board_coverage_issues()['index_gaps']
        assert '滞后 1 个交易日' in issues[0]['detail']
    else:
        calendar.execute("INSERT INTO index_bar(index_code,trade_date,close) VALUES ('000001.SH','2026-10-16',10)")
        report.scan_market_index_quality()
        issue = calendar.query_df("SELECT detail FROM data_quality_issue "
                                  "WHERE code='000001.SH' AND issue_type='market_index_gap'").iloc[0]
        assert '滞后 1 个交易日' in issue['detail']


def test_ignored_legacy_issue_display_updates_without_changing_audit(calendar, monkeypatch):
    from backend.api import data_admin
    original = json.dumps({'periods': ['即时'], 'message':
        '资金流滞后：即时最新 2026-10-16（滞后 3 天）；全局最新交易日 2026-10-19，待重采资金流'},
        ensure_ascii=False)
    calendar.execute("INSERT INTO data_quality_issue "
                     "(id,issue_type,trade_date,severity,status,detail,ignore_scope,ignore_active,detected_at) "
                     "VALUES (101,'board_fund_stale','2026-10-19','mid','ignored',?,'occurrence',TRUE,now())",
                     [original])
    monkeypatch.setattr(data_admin, 'get_client', lambda: calendar)
    result = data_admin.quality(status='ignored').data['list'][0]
    assert '滞后 1 个交易日' in json.loads(result['detail'])['message']
    assert result['status'] == 'ignored' and result['ignore_active'] is True
    assert calendar.query_df('SELECT detail FROM data_quality_issue WHERE id=101').iloc[0, 0] == original


def test_legacy_batch_loads_calendar_once_and_preserves_repair_reason(calendar, monkeypatch):
    report = DataIntegrityReport(calendar)
    rows = [{'issue_type': 'board_fund_stale', 'trade_date': '2026-10-19', 'detail':
             json.dumps({'message': '即时最新 2026-10-16（滞后 3 天）；最近修复未完成：连接失败'})}
            for _ in range(500)]
    queries = []
    query = calendar.query_df
    def counted(sql, *args, **kwargs):
        queries.append(sql)
        return query(sql, *args, **kwargs)
    monkeypatch.setattr(calendar, 'query_df', counted)
    report.normalize_legacy_fund_lags(rows)
    assert len(queries) == 1
    assert all('滞后 1 个交易日' in row['detail'] and '连接失败' in row['detail'] for row in rows)


def test_missing_calendar_never_falls_back_to_natural_days(market):
    rows = [{'issue_type': 'board_fund_stale', 'trade_date': '2026-10-19',
             'detail': '即时最新 2026-10-16（滞后 3 天）'}]
    DataIntegrityReport(market).normalize_legacy_fund_lags(rows)
    assert '交易日数待核验' in rows[0]['detail']
    assert '滞后 3 天' not in rows[0]['detail']
