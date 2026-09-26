import pytest

from backend.services.listed_boards import listed_board_labels, parse_listed_board_keys
from backend.services.stock_board_filters import parse_stock_board_values


def test_parse_listed_board_keys_deduplicates_and_maps_labels():
    keys = parse_listed_board_keys("main,gem,main")

    assert keys == ["main", "gem"]
    assert listed_board_labels(keys) == ["主板", "创业板"]


def test_parse_listed_board_keys_rejects_unknown_value():
    with pytest.raises(ValueError, match="不支持的上市板块"):
        parse_listed_board_keys("main,unknown")


def test_stock_board_values_keep_page_specific_semantics():
    assert parse_stock_board_values("主板,ST,退市,主板") == ["主板", "ST", "退市"]

    with pytest.raises(ValueError, match="不支持的个股板块"):
        parse_stock_board_values("main")
