"""Labels were retired from daily updates at the user's request."""

LABEL_UPDATES_FROZEN = True
FROZEN_SINCE = '2026-10-19'
FROZEN_MESSAGE = '标签数据已冻结，停止更新；保留历史结果供查询。'
FROZEN_STEP_KEYS = frozenset({
    'label_evidence', 'stockout_historical_operating', 'label_analysis',
})


class LabelUpdatesFrozenError(RuntimeError):
    pass


def require_label_updates_enabled() -> None:
    if LABEL_UPDATES_FROZEN:
        raise LabelUpdatesFrozenError(FROZEN_MESSAGE)


def skip_frozen_label_update() -> bool:
    if LABEL_UPDATES_FROZEN:
        print(f'[skipped] {FROZEN_MESSAGE} 冻结日期：{FROZEN_SINCE}')
        return True
    return False
