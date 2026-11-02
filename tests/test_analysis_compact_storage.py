from datetime import date
from unittest.mock import MagicMock
from app.services.label_analysis_materialized import encode_history,decode_history,split_row,join_row,MaterializedAnalysisRepository
from etl.label_analysis_refresh import ResultWriter


def test_compact_period_is_lossless_for_nulls_labels_ratios_and_coverage():
    conn=MagicMock();writer=ResultWriter(conn,'batch',date(2026,10,16),storage='analysis-read-model-v3-compact')
    row={'key':'x','labels':[{'id':201,'parent_id':2,'period':'30d'}],
         'ratio_pairs':{'margin':[None,0]},'observed_days':{'sales_qty':0},
         'values':{'sales_qty':None,'sessions_total':0},'daily':{'raw':'must stay in history'}}
    writer.ids[('business_unit','x')]=7
    writer.period([row],'business_unit',30,'current')
    args=conn.cursor.return_value.__enter__.return_value.executemany.call_args.args
    assert 'dashboard_analysis_compact_period' in args[0]
    record=args[1][0];restored=decode_history(record[-2],record[-1])
    context,domains=split_row(row);context.update(_object_id=7,_batch_id='batch')
    assert restored==join_row(context,domains)
    assert 'daily' not in restored


def test_compact_reader_verifies_checksum_and_reads_bounded_chunks():
    row={'key':'x','values':{'sales_qty':None},'ratio_pairs':{'margin':[None,0]}}
    blob,checksum=encode_history(row);cur=MagicMock()
    cur.fetchmany.side_effect=[[{'payload':blob,'checksum':checksum}],[]]
    assert MaterializedAnalysisRepository._rows(cur,'b',date(2026,10,16),30,'country','current',storage='analysis-read-model-v3-compact')==[row]
    assert 'dashboard_analysis_compact_period' in cur.execute.call_args.args[0]
    assert cur.fetchmany.call_args_list[0].args==(40,)
