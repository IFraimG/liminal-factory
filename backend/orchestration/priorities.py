"""Per-episode agent order, separate from transient task results."""
from backend.orchestration.workflow import DAG,GATES

PROVIDERS=('codex','antigravity','kimi')
AI_TASKS={'music_brief','visual_reference','unity_preview','metadata','recording_setup'}
LOCAL_TASKS=set(DAG)-GATES-AI_TASKS
ACTIVE_STATUSES={'Running','Waiting for Client','Waiting for CLI','Waiting for Permission','Waiting for quota'}

def validate_order(order):
    if not isinstance(order,list) or len(order)!=len(PROVIDERS) or any(not isinstance(p,str) for p in order) or set(order)!=set(PROVIDERS):
        raise ValueError('Use each agent exactly once: codex, antigravity, kimi')
    return list(order)

def default_order(provider,task):
    first='antigravity' if provider=='gemini' else provider
    order=[first,*[p for p in PROVIDERS if p!=first]]
    if order.index('antigravity')>order.index('kimi'):
        order.remove('antigravity');order.insert(order.index('kimi'),'antigravity')
    return order

def order_for(config,provider,task):
    return list(config.get('agent_priorities',{}).get(task) or default_order(provider,task))
