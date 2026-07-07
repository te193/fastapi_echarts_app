(async function () {
  const fmt = new Intl.NumberFormat('zh-CN');
  const money = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 });
  const $ = (id) => document.getElementById(id);

  const order = [
    'returned_not_arrived',
    'returned_receiving',
    'returned_observation_period',
    'returned_operation_period',
    'returned_with_sales',
    'exited_return',
  ];
  const colors = {
    exited_return: '#b42318',
    returned_with_sales: '#15803d',
    returned_observation_period: '#b45309',
    returned_operation_period: '#7c3aed',
    returned_receiving: '#0f766e',
    returned_not_arrived: '#2563eb',
    inbound: '#0ea5e9',
    sales: '#b42318',
    slate: '#475569',
  };
  const labels = {
    exited_return: '已退出返场',
    returned_with_sales: '已返场销售',
    returned_observation_period: '返场观察期',
    returned_operation_period: '返场运营期',
    returned_receiving: '返场接收中',
    returned_not_arrived: '返场未到货',
  };
  const statusClass = {
    exited_return: 'red',
    returned_with_sales: 'green',
    returned_observation_period: 'amber',
    returned_operation_period: 'purple',
    returned_receiving: 'teal',
    returned_not_arrived: 'blue',
  };

  let data;
  let activeStatus = 'returned_with_sales';

  try {
    data = await fetch(`./static/returned-product-tags/returned-product-tags-data.json?t=${Date.now()}`).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    });
  } catch (error) {
    document.querySelector('main').innerHTML = `<div class="error">数据加载失败：${escapeHtml(error.message)}</div>`;
    return;
  }

  const cohortByMsku = new Map((data.cohort_items || []).map((row) => [row.msku, row]));

  function n(value) {
    return Number(value || 0);
  }

  function pct(value, total) {
    return total ? `${(n(value) / total * 100).toFixed(1)}%` : '-';
  }

  function rate(value) {
    return `${(n(value) * 100).toFixed(1)}%`;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[char]));
  }

  function dateText(value) {
    return value ? new Date(value).toLocaleDateString('zh-CN') : '-';
  }

  function statusLabel(status) {
    return labels[status] || status;
  }

  function byStatus(status) {
    return data.summary_by_status.find((row) => row.status === status) || {
      status,
      label: statusLabel(status),
      msku_count: 0,
      asin_count: 0,
      current_fba_available: 0,
      current_fba_inbound: 0,
      current_fba_available_purchase_cost: 0,
      current_fba_inbound_purchase_cost: 0,
      sales_qty_14d: 0,
      sales_qty_21d: 0,
      avg_longest_stockout_days: 0,
      max_longest_stockout_days: 0,
    };
  }

  $('scope').textContent = [
    `run_id ${data.scope?.run_id || '-'}`,
    `${dateText(data.scope?.window_180_start)} 至 ${dateText(data.scope?.latest_inventory_date)}`,
    `生成 ${new Date(data.generated_at).toLocaleString('zh-CN')}`,
  ].join('；');

  const statusRows = order.map(byStatus);
  const exited = byStatus('exited_return');
  const sold = byStatus('returned_with_sales');
  const observation = byStatus('returned_observation_period');
  const operation = byStatus('returned_operation_period');
  const receiving = byStatus('returned_receiving');
  const notArrived = byStatus('returned_not_arrived');
  const day7 = (data.cohort_by_day || []).find((row) => row.day === 7) || {};
  const day14 = (data.cohort_by_day || []).find((row) => row.day === 14) || {};
  const day21 = (data.cohort_by_day || []).find((row) => row.day === 21) || {};

  $('kpis').innerHTML = [
    ['返场 MSKU', fmt.format(data.summary.total_msku), `覆盖 ASIN ${fmt.format(data.summary.total_asin)}`, 'blue'],
    ['返场未到货', fmt.format(notArrived.msku_count), `FBA在途 ${fmt.format(n(notArrived.current_fba_inbound))}`, 'blue'],
    ['返场接收中', fmt.format(receiving.msku_count), '0 < FBA可售 < 10', 'teal'],
    ['返场观察期', fmt.format(observation.msku_count), 'D0-D3，先观察', 'amber'],
    ['返场运营期', fmt.format(operation.msku_count), 'D4-D21，需要运营介入', 'purple'],
    ['已返场销售', fmt.format(sold.msku_count), `21天销量 ${fmt.format(sold.sales_qty_21d)}`, 'green'],
    ['已退出返场', fmt.format(exited.msku_count), `闭环率 ${rate(data.summary.return_closure_rate)}`, 'red'],
  ].map(([label, value, foot, cls]) => `
    <article class="panel kpi">
      <div class="label">${label}</div>
      <div class="value ${cls}">${value}</div>
      <div class="foot">${foot}</div>
    </article>
  `).join('');

  function barChart(rows, fields, options = {}) {
    const width = options.width || 760;
    const height = options.height || 340;
    const pad = { left: 118, right: 28, top: 22, bottom: 34 };
    const max = Math.max(1, ...rows.flatMap((row) => fields.map((field) => n(row[field.key]))));
    const groupH = (height - pad.top - pad.bottom) / Math.max(1, rows.length);
    const barH = Math.min(16, groupH / (fields.length + 1));
    const x = (value) => pad.left + n(value) / max * (width - pad.left - pad.right);
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(options.title || 'bar chart')}">
      ${[0, .25, .5, .75, 1].map((tick) => {
        const xx = pad.left + tick * (width - pad.left - pad.right);
        return `<line x1="${xx}" y1="${pad.top}" x2="${xx}" y2="${height - pad.bottom}" stroke="#e5eaf0"/>
          <text x="${xx}" y="${height - 12}" text-anchor="middle" fill="#64748b" font-size="11">${fmt.format(Math.round(max * tick))}</text>`;
      }).join('')}
      ${rows.map((row, rowIndex) => {
        const label = statusLabel(row.status || row.label);
        const baseY = pad.top + rowIndex * groupH + groupH * .22;
        return `<text x="8" y="${baseY + barH}" fill="#334155" font-size="12">${escapeHtml(label)}</text>
          ${fields.map((field, fieldIndex) => {
            const y = baseY + fieldIndex * (barH + 5);
            const value = n(row[field.key]);
            const w = Math.max(0, x(value) - pad.left);
            return `<rect x="${pad.left}" y="${y}" width="${w}" height="${barH}" rx="3" fill="${field.color}">
                <title>${escapeHtml(label)} ${escapeHtml(field.label)} ${fmt.format(value)}</title>
              </rect>
              <text x="${Math.min(width - pad.right, pad.left + w + 5)}" y="${y + barH - 4}" fill="#334155" font-size="11">${fmt.format(value)}</text>`;
          }).join('')}`;
      }).join('')}
    </svg>`;
  }

  function lineChart(rows, fields, options = {}) {
    const width = options.width || 760;
    const height = options.height || 330;
    const pad = { left: 58, right: 28, top: 24, bottom: 42 };
    const max = Math.max(1, ...rows.flatMap((row) => fields.map((field) => n(row[field.key]))));
    const step = rows.length > 1 ? (width - pad.left - pad.right) / (rows.length - 1) : 0;
    const x = (index) => pad.left + index * step;
    const y = (value) => height - pad.bottom - n(value) / max * (height - pad.top - pad.bottom);
    const formatAxis = options.percent ? (value) => `${Math.round(value * 100)}%` : (value) => fmt.format(Math.round(value));
    const formatPoint = options.percent ? (value) => `${(value * 100).toFixed(1)}%` : (value) => fmt.format(value);
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(options.title || 'line chart')}">
      ${[0, .25, .5, .75, 1].map((tick) => {
        const yy = height - pad.bottom - tick * (height - pad.top - pad.bottom);
        return `<line x1="${pad.left}" y1="${yy}" x2="${width - pad.right}" y2="${yy}" stroke="#e5eaf0"/>
          <text x="8" y="${yy + 4}" fill="#64748b" font-size="11">${formatAxis(max * tick)}</text>`;
      }).join('')}
      ${fields.map((field) => {
        const path = rows.map((row, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(row[field.key]).toFixed(1)}`).join(' ');
        return `<path d="${path}" fill="none" stroke="${field.color}" stroke-width="3"/>
          ${rows.map((row, index) => `<circle cx="${x(index)}" cy="${y(row[field.key])}" r="3" fill="${field.color}">
            <title>D${row.day} ${escapeHtml(field.label)} ${formatPoint(n(row[field.key]))}</title>
          </circle>`).join('')}`;
      }).join('')}
      ${rows.map((row, index) => `<text x="${x(index)}" y="${height - 15}" text-anchor="middle" fill="#64748b" font-size="11">D${row.day}</text>`).join('')}
    </svg>`;
  }

  function legend(items) {
    return items.map(([label, color]) => `<span><i style="background:${color}"></i>${label}</span>`).join('');
  }

  $('stageChart').innerHTML = barChart(statusRows, [
    { key: 'msku_count', label: 'MSKU', color: colors.returned_with_sales },
    { key: 'asin_count', label: 'ASIN', color: colors.returned_not_arrived },
  ], { title: '返场阶段规模' });
  $('stageLegend').innerHTML = legend([['MSKU', colors.returned_with_sales], ['ASIN', colors.returned_not_arrived]]);

  $('stockSalesChart').innerHTML = barChart(statusRows, [
    { key: 'current_fba_available', label: 'FBA可售', color: colors.returned_with_sales },
    { key: 'current_fba_inbound', label: 'FBA在途', color: colors.inbound },
    { key: 'sales_qty_21d', label: '21天销量', color: colors.sales },
  ], { title: '库存与21天销售' });
  $('stockSalesLegend').innerHTML = legend([
    ['FBA可售', colors.returned_with_sales],
    ['FBA在途', colors.inbound],
    ['21天销量', colors.sales],
  ]);

  $('cohortKpis').innerHTML = [
    ['Cohort MSKU', fmt.format(data.cohort_summary?.cohort_msku || 0), `完整 D21 样本 ${fmt.format(data.cohort_summary?.complete_21d_msku || 0)}`, 'blue'],
    ['D7 累计销量', fmt.format(n(day7.cumulative_sales_qty)), `累计出单率 ${pct(day7.cumulative_with_sales_msku, day7.observable_msku)}`, 'green'],
    ['D14 累计销量', fmt.format(n(day14.cumulative_sales_qty)), `累计出单率 ${pct(day14.cumulative_with_sales_msku, day14.observable_msku)}`, 'green'],
    ['D21 累计销量', fmt.format(n(day21.cumulative_sales_qty)), `可观察样本 ${fmt.format(n(day21.observable_msku))}`, 'green'],
  ].map(([label, value, foot, cls]) => `
    <article class="panel kpi">
      <div class="label">${label}</div>
      <div class="value ${cls}">${value}</div>
      <div class="foot">${foot}</div>
    </article>
  `).join('');

  $('cohortSalesChart').innerHTML = lineChart(data.cohort_by_day || [], [
    { key: 'cumulative_sales_qty', label: '累计销量', color: colors.returned_with_sales },
    { key: 'observable_msku', label: '可观察MSKU', color: colors.returned_not_arrived },
    { key: 'no_sales_yet_msku', label: '仍未出单MSKU', color: colors.sales },
  ], { title: 'D0-D21累计销量与样本数' });
  $('cohortSalesLegend').innerHTML = legend([
    ['累计销量', colors.returned_with_sales],
    ['可观察MSKU', colors.returned_not_arrived],
    ['仍未出单MSKU', colors.sales],
  ]);

  $('cohortTable').innerHTML = `
    <table>
      <thead>
        <tr>
          <th>返场Day</th><th class="num">可观察MSKU</th><th class="num">当天出单MSKU</th><th class="num">累计出单MSKU</th><th class="num">当天出单率</th><th class="num">累计出单率</th><th class="num">当天销量</th><th class="num">累计销量</th><th class="num">平均销量</th><th class="num">FBA可售</th><th class="num">库存消耗率</th><th class="num">仍未出单</th>
        </tr>
      </thead>
      <tbody>
        ${(data.cohort_by_day || []).map((row) => `<tr>
          <td>D${row.day}</td>
          <td class="num">${fmt.format(row.observable_msku)}</td>
          <td class="num">${fmt.format(row.with_sales_msku)}</td>
          <td class="num">${fmt.format(row.cumulative_with_sales_msku)}</td>
          <td class="num">${rate(row.order_rate)}</td>
          <td class="num">${rate(row.cumulative_order_rate)}</td>
          <td class="num">${fmt.format(row.sales_qty)}</td>
          <td class="num">${fmt.format(row.cumulative_sales_qty)}</td>
          <td class="num">${row.avg_sales_qty}</td>
          <td class="num">${fmt.format(row.fba_available)}</td>
          <td class="num">${rate(row.stock_consumption_rate)}</td>
          <td class="num">${fmt.format(row.no_sales_yet_msku)}</td>
        </tr>`).join('')}
      </tbody>
    </table>
  `;

  $('summaryTable').innerHTML = `
    <table>
      <thead>
        <tr>
          <th>阶段</th><th class="num">MSKU</th><th class="num">ASIN</th><th class="num">FBA可售</th><th class="num">FBA在途</th><th class="num">21天销量</th><th class="num">FBA可售成本</th><th class="num">FBA在途成本</th><th class="num">最长缺货天数</th>
        </tr>
      </thead>
      <tbody>
        ${statusRows.map((row) => `<tr>
          <td><span class="tag">${statusLabel(row.status)}</span></td>
          <td class="num">${fmt.format(row.msku_count)}</td>
          <td class="num">${fmt.format(row.asin_count)}</td>
          <td class="num">${fmt.format(row.current_fba_available)}</td>
          <td class="num">${fmt.format(row.current_fba_inbound)}</td>
          <td class="num">${fmt.format(row.sales_qty_21d)}</td>
          <td class="num">${money.format(row.current_fba_available_purchase_cost)}</td>
          <td class="num">${money.format(row.current_fba_inbound_purchase_cost)}</td>
          <td class="num">${fmt.format(row.max_longest_stockout_days)}</td>
        </tr>`).join('')}
      </tbody>
    </table>
  `;

  function rowsForStatus(status) {
    return (data.detail || []).filter((row) => row.status === status);
  }

  function returnDayLabel(msku) {
    const row = cohortByMsku.get(msku);
    return row ? `D${n(row.observed_days)}` : '-';
  }

  function renderTabs() {
    $('tabs').innerHTML = order.map((status) => {
      const row = byStatus(status);
      const active = status === activeStatus ? ' active' : '';
      return `<button class="${active}" data-status="${status}">${statusLabel(status)} ${fmt.format(row.msku_count)}</button>`;
    }).join('') + '<button id="exportCsv">导出CSV</button>';

    $('tabs').querySelectorAll('button[data-status]').forEach((button) => {
      button.addEventListener('click', () => {
        activeStatus = button.dataset.status;
        renderTabs();
        renderDetail();
      });
    });
    $('exportCsv').addEventListener('click', exportCsv);
  }

  function renderDetail() {
    const rows = rowsForStatus(activeStatus);
    $('detailTable').innerHTML = `
      <table>
        <thead>
          <tr>
            <th>MSKU</th><th>SKU</th><th>ASIN</th><th>店铺</th><th>产品名</th><th>返场Day</th><th class="num">FBA可售</th><th class="num">FBA在途</th><th class="num">21天销量</th><th class="num">180天缺货</th><th class="num">最长连续缺货</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((row) => `<tr>
            <td>${escapeHtml(row.msku)}</td>
            <td>${escapeHtml(row.sku)}</td>
            <td>${escapeHtml(row.asin)}</td>
            <td>${escapeHtml(row.seller_name_new)}</td>
            <td>${escapeHtml(row.product_name)}</td>
            <td>${returnDayLabel(row.msku)}</td>
            <td class="num">${fmt.format(row.current_fba_available)}</td>
            <td class="num">${fmt.format(row.current_fba_inbound)}</td>
            <td class="num">${fmt.format(row.sales_qty_21d)}</td>
            <td class="num">${fmt.format(row.stockout_days_180d)}</td>
            <td class="num">${fmt.format(row.max_consecutive_stockout_days_180d)}</td>
          </tr>`).join('')}
        </tbody>
      </table>
    `;
  }

  function exportCsv() {
    const rows = rowsForStatus(activeStatus);
    const headers = ['status', 'label', 'msku', 'sku', 'asin', 'seller_name_new', 'product_name', 'return_day_label', 'current_fba_available', 'current_fba_inbound', 'sales_qty_21d', 'stockout_days_180d', 'max_consecutive_stockout_days_180d'];
    const csv = [
      headers.join(','),
      ...rows.map((row) => headers.map((key) => {
        const value = key === 'label' ? statusLabel(row.status) : key === 'return_day_label' ? returnDayLabel(row.msku) : row[key];
        return `"${String(value ?? '').replace(/"/g, '""')}"`;
      }).join(',')),
    ].join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `returned-products-${activeStatus}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  renderTabs();
  renderDetail();
})();
