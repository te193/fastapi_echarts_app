WITH
参数 AS (
    SELECT CAST(35 AS DECIMAL(10, 2)) AS 安全库存天数
),
销售角色 AS (
    SELECT
        t.data_date AS 标签数据日期,
        t.country_category AS 站点,
        t.store AS 店铺名,
        t.msku AS MSKU,
        d.sub_label_name AS 全站点销售角色
    FROM dws_datasync.dws_标签表 AS t
    INNER JOIN dws_datasync.dws_标签详情表 AS d
        ON d.sub_label_id = t.label_id
       AND d.label_name = '销售角色'
       AND d.status = '启用'
    WHERE t.data_date = (
              SELECT MAX(data_date)
              FROM dws_datasync.dws_标签表
          )
      AND t.country IS NULL              -- 全站点口径
      AND t.label_period = '30d'          -- 使用30天销售角色
),
最新库存 AS (
    SELECT
        数据日期,
        店铺名,
        站点,
        MSKU,
        ASIN,
        FNSKU,
        可用库存,
        可售库存,
        实际在途,
        本地仓数量,
        本地可用,
        采购在途,
        采购计划,
        待检待上架量,
        日均销量,
        可售天数,
        近3天销量,
        近3天FBA可售天数,
        近7天销量,
        近7天FBA可售天数,
        近14天销量,
        近14天FBA可售天数,
        近30天销量,
        近30天FBA可售天数
    FROM dws_datasync.dws_库存宽表
    WHERE 数据日期 = (
        SELECT MAX(数据日期)
        FROM dws_datasync.dws_库存宽表
    )
),
库存汇总 AS (
    SELECT
        k.数据日期,
        k.店铺名,
        k.站点,
        k.MSKU,
        GROUP_CONCAT(DISTINCT k.ASIN ORDER BY k.ASIN SEPARATOR ',') AS ASIN,
        GROUP_CONCAT(DISTINCT k.FNSKU ORDER BY k.FNSKU SEPARATOR ',') AS FNSKU,

        -- FBA库存按仓库拆分，需要求和
        SUM(COALESCE(k.可用库存, 0)) AS 可用库存,
        SUM(COALESCE(k.可售库存, 0)) AS 可售库存,
        SUM(COALESCE(k.实际在途, 0)) AS 实际在途,

        -- 以下指标会在不同仓库行重复，只取一个值
        MAX(k.本地仓数量) AS 本地仓数量,
        MAX(k.本地可用) AS 本地可用,
        MAX(k.采购在途) AS 采购在途,
        MAX(k.采购计划) AS 采购计划,
        MAX(k.待检待上架量) AS 待检待上架量,
        MAX(k.日均销量) AS 日均销量,
        MAX(k.可售天数) AS 可售天数,
        MAX(k.近3天销量) AS 近3天销量,
        MAX(k.近3天FBA可售天数) AS 近3天历史有货天数,
        MAX(k.近7天销量) AS 近7天销量,
        MAX(k.近7天FBA可售天数) AS 近7天历史有货天数,
        MAX(k.近14天销量) AS 近14天销量,
        MAX(k.近14天FBA可售天数) AS 近14天历史有货天数,
        MAX(k.近30天销量) AS 近30天销量,
        MAX(k.近30天FBA可售天数) AS 近30天历史有货天数
    FROM 最新库存 AS k
    GROUP BY
        k.数据日期,
        k.店铺名,
        k.站点,
        k.MSKU
),
库存明细 AS (
    SELECT
        k.数据日期,
        k.店铺名,
        k.站点,
        k.MSKU,
        k.ASIN,
        k.FNSKU,
        k.可用库存,
        k.可售库存,
        k.实际在途,
        k.本地仓数量,
        k.本地可用,
        k.采购在途,
        k.采购计划,
        k.待检待上架量,
        k.日均销量,
        k.可售天数,
        ROUND(k.可售库存 / NULLIF(k.日均销量, 0), 2) AS 可售库存支撑天数,
        k.近3天销量,
        k.近3天历史有货天数,
        k.近7天销量,
        k.近7天历史有货天数,
        k.近14天销量,
        k.近14天历史有货天数,
        k.近30天销量,
        k.近30天历史有货天数,
        r.标签数据日期,
        r.全站点销售角色
    FROM 库存汇总 AS k
    LEFT JOIN 销售角色 AS r
        ON r.站点 = k.站点
       AND r.店铺名 = k.店铺名
       AND r.MSKU = k.MSKU
)
SELECT
    k.数据日期,
    k.标签数据日期,
    k.店铺名,
    k.站点,
    k.MSKU,
    k.ASIN,
    k.FNSKU,
    k.全站点销售角色,
    k.可用库存,
    k.可售库存,
    k.实际在途,
    k.本地仓数量,
    k.本地可用,
    k.采购在途,
    k.采购计划,
    k.待检待上架量,
    k.日均销量,
    k.可售天数,
    k.可售库存支撑天数,
    k.近3天销量,
    k.近3天历史有货天数,
    k.近7天销量,
    k.近7天历史有货天数,
    k.近14天销量,
    k.近14天历史有货天数,
    k.近30天销量,
    k.近30天历史有货天数,
    CASE
        WHEN k.全站点销售角色 NOT IN ('明星产品', '潜力产品')
             OR k.全站点销售角色 IS NULL
            THEN '不适用'
        WHEN k.可售库存支撑天数 IS NULL
            THEN '数据不足'
        WHEN k.可售库存支撑天数 > p.安全库存天数
            THEN '安全'
        ELSE '库存预警'
    END AS 安全库存判断
FROM 库存明细 AS k
CROSS JOIN 参数 AS p;
