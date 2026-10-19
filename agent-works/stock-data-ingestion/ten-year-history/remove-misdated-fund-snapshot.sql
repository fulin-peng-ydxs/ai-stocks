-- 上轮修复于2026-10-19从实时源获取、误标2026-10-16的唯一新增行。
-- 已对比修复前备份确认不存在原记录；只匹配已取证的完整数值。
BEGIN TRANSACTION;
DELETE FROM board_fund_flow
WHERE board_code='309274' AND snapshot_date=DATE '2026-10-16' AND period='5日'
  AND inflow=90.73 AND outflow=100.32 AND net_inflow=-9.59 AND net_ratio=-6.52;
COMMIT;
