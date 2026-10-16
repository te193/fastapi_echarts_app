from app.services.label_analysis_metrics import METRICS
from app.services.label_analysis_service import AnalysisQuery


def test_a_query_can_select_the_entire_registered_metric_catalog():
    columns=list(METRICS)
    query=AnalysisQuery(columns=columns)
    assert query.columns==columns
