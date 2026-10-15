from fastapi.testclient import TestClient
from unittest.mock import patch

from app import main


def test_new_page_and_old_page_coexist():
    with TestClient(main.app) as client:
        new=client.get('/return-goods-strategy')
        assert new.status_code==200
        assert '返场品运营策略' in new.text
        assert 'strategyTable' in new.text
        assert client.get('/return-goods').status_code==200


def test_readonly_api_filters_and_validation():
    with patch('app.main.return_goods_strategy_service') as service,TestClient(main.app) as client:
        service.get_payload.return_value={'items':[]}
        result=client.get('/api/return-goods-strategy?exit_status=tracking&state=poor&action=price_down&stage=intervene&age_band=d8_14&focus=price&all_rows=true')
        assert result.status_code==200
        assert service.get_payload.call_args.kwargs['action']=='price_down'
        assert service.get_payload.call_args.kwargs['stage']=='intervene'
        assert service.get_payload.call_args.kwargs['age_band']=='d8_14'
        assert service.get_payload.call_args.kwargs['focus']=='price'
        assert service.get_payload.call_args.kwargs['all_rows'] is True
        assert client.get('/api/return-goods-strategy?snapshot_date=bad').status_code==422
        assert client.get('/api/return-goods-strategy?page=0').status_code==422
        assert client.post('/api/return-goods-strategy',json={}).status_code==405


def test_detail_pinned_to_batch_and_missing_event_404():
    with patch('app.main.return_goods_strategy_service') as service,TestClient(main.app) as client:
        service.get_detail.return_value=None
        result=client.get('/api/return-goods-strategy/detail?batch_id=1&event_id=abc')
        assert result.status_code==404
        service.get_detail.assert_called_once_with(event_id='abc',batch_id=1)
