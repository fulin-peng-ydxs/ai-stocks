-- 配置管理拆页 + 评分方案公开能力资源码（幂等）
-- IA：系统管理 -> 配置管理，下设评分规则/买卖指标/技术指标/系统设置。
-- 评分规则和买卖指标为业务可授权；技术指标和系统设置仍 system-only。
-- 运行期菜单和功能点以 PostgreSQL 为事实源：本脚本只补缺失行，不覆盖已存在配置。
-- 如需改变父级、标题、路由、可见性或排序，必须由系统管理员通过管理页面/API 显式操作，
-- 以便执行校验、权限版本失效和 before/after 审计。

BEGIN;

INSERT INTO sys_menu (id, parent_id, code, title, type, route_path, icon, sort, visible, is_builtin)
VALUES
  ('/system/config', 'system', '/system/config', '配置管理', 'group', NULL, 'Files', 10, 'login', TRUE),
  ('/system/config/score', '/system/config', '/system/config/score', '评分规则', 'leaf', '/system/config/score', NULL, 10, 'login', TRUE),
  ('/system/config/trade', '/system/config', '/system/config/trade', '买卖指标', 'leaf', '/system/config/trade', NULL, 20, 'login', TRUE),
  ('/system/config/tech', '/system/config', '/system/config/tech', '技术指标', 'leaf', '/system/config/tech', NULL, 30, 'system', TRUE),
  ('/system/config/system', '/system/config', '/system/config/system', '系统设置', 'leaf', '/system/config/system', NULL, 40, 'system', TRUE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO sys_resource (id, menu_id, code, name, type, api_method, api_path, sort, is_builtin)
VALUES
  ('score:run', '/system/config/score', 'score:run', '评分方案打分', 'api', 'POST', '/api/score-profiles/run', 10000, TRUE),
  ('score-profile:view', '/system/config/score', 'score-profile:view', '查看评分方案', 'api', 'GET', '/api/score-profiles', 10010, TRUE),
  ('score-profile:save', '/system/config/score', 'score-profile:save', '保存评分方案', 'api', 'POST', '/api/score-profiles', 10020, TRUE),
  ('score-profile:delete', '/system/config/score', 'score-profile:delete', '删除评分方案', 'api', 'DELETE', '/api/score-profiles/{pid}', 10030, TRUE),
  ('score-profile:publish-tenant', '/system/config/score', 'score-profile:publish-tenant', '租户内公开评分方案', 'api', 'POST', '/api/score-profiles/{pid}/visibility', 10040, TRUE),
  ('score-profile:publish-public', '/system/config/score', 'score-profile:publish-public', '全体公开评分方案', 'api', 'POST', '/api/score-profiles/{pid}/visibility', 10050, TRUE),
  ('trade-profile:view', '/system/config/trade', 'trade-profile:view', '查看买卖方案', 'api', 'GET', '/api/trade-profiles', 10060, TRUE),
  ('trade-profile:save', '/system/config/trade', 'trade-profile:save', '保存买卖方案', 'api', 'POST', '/api/trade-profiles', 10070, TRUE),
  ('trade-profile:delete', '/system/config/trade', 'trade-profile:delete', '删除买卖方案', 'api', 'DELETE', '/api/trade-profiles/{pid}', 10080, TRUE),
  ('trade-profile:preview', '/system/config/trade', 'trade-profile:preview', '买卖条件试算', 'api', 'POST', '/api/trade-profiles/preview', 10090, TRUE),
  ('indicator:def-manage', '/system/config/tech', 'indicator:def-manage', '技术指标定义维护', 'api', 'POST', '/api/indicators/def', 10100, TRUE),
  ('config:view', '/system/config/system', 'config:view', '查看系统配置', 'api', 'GET', '/api/config', 10110, TRUE),
  ('config:reload', '/system/config/system', 'config:reload', '重载系统配置', 'api', 'POST', '/api/config/reload', 10120, TRUE)
ON CONFLICT (id) DO NOTHING;

INSERT INTO sys_role_menu (role_id, menu_id)
SELECT r.id, x.menu_id
FROM sys_role r
CROSS JOIN (
  VALUES
    ('system'),
    ('/system/config'),
    ('/system/config/score'),
    ('/system/config/trade')
) AS x(menu_id)
WHERE r.id IN ('tenant_admin', 'normal')
ON CONFLICT DO NOTHING;

-- 评分/买卖业务码默认给业务角色；租户公开默认仅给 tenant_admin，normal 需单独授权。
INSERT INTO sys_role_resource (role_id, resource_id)
SELECT r.id, x.resource_id
FROM sys_role r
CROSS JOIN (
  VALUES
    ('score:run'),
    ('score-profile:view'),
    ('score-profile:save'),
    ('score-profile:delete'),
    ('trade-profile:view'),
    ('trade-profile:save'),
    ('trade-profile:delete'),
    ('trade-profile:preview')
) AS x(resource_id)
WHERE r.id IN ('tenant_admin', 'normal')
ON CONFLICT DO NOTHING;

INSERT INTO sys_role_resource (role_id, resource_id)
VALUES ('tenant_admin', 'score-profile:publish-tenant')
ON CONFLICT DO NOTHING;

DELETE FROM sys_role_resource
WHERE role_id = 'normal'
  AND resource_id = 'score-profile:publish-tenant';

-- 授权/菜单口径变更后让既有在线 token 失效，避免继续使用旧权限快照。
UPDATE sys_user u
SET perm_ver = perm_ver + 1
WHERE EXISTS (
  SELECT 1
  FROM sys_user_role ur
  WHERE ur.user_id = u.id
    AND ur.role_id IN ('tenant_admin', 'normal')
);

COMMIT;
