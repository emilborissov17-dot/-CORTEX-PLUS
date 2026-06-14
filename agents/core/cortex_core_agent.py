from __future__ import annotations
import json, pathlib
from dataclasses import dataclass
from typing import Protocol
from core import goals
from core import llm_backend

BASE_DIR    = pathlib.Path(__file__).resolve().parents[2]
MASTER_PATH = BASE_DIR / 'snapshots' / 'master' / 'master_snapshot_latest.json'
TRENDS_PATH  = BASE_DIR / 'memory' / 'trends_latest.json'
LEVELS_PATH  = BASE_DIR / 'memory' / 'auto_levels.json'

def _load_auto_levels() -> dict:
    try:
        return {k: v['level'] for k, v in json.loads(LEVELS_PATH.read_text(encoding='utf-8')).items()}
    except Exception:
        return {}
NEWS_PATH   = BASE_DIR / 'news' / 'news_latest.json'

def _load_news_context() -> str:
    try:
        news = json.loads(NEWS_PATH.read_text(encoding='utf-8'))
        results = news.get('results', {})
        lines = [f"INTERNET INTELLIGENCE ({news.get('date','')}) — {len(results)} axes monitored:"]
        critical = news.get('critical_axes', [])
        high     = news.get('high_urgency_axes', [])
        if critical: lines.append(f"  CRITICAL ALERTS: {', '.join(critical)}")
        if high:     lines.append(f"  HIGH URGENCY:    {', '.join(high)}")
        lines.append("")
        # Само HIGH и CRITICAL оси за да пестим токени
        for axis, r in results.items():
            urgency = r.get('urgency', 'LOW')
            if urgency not in ('CRITICAL', 'HIGH'):
                continue
            summary = r.get('summary', '')[:120]
            icon = "CRITICAL" if urgency == "CRITICAL" else "HIGH"
            lines.append(f"[{icon}] {axis}: {summary}")
        return '\n'.join(lines)
    except Exception as e:
        return f"[news unavailable: {e}]"


class LLMCall(Protocol):
    def __call__(self, prompt: str) -> str: ...

def _load_civilization_state() -> str:
    lines = []
    try:
        master = json.loads(MASTER_PATH.read_text(encoding='utf-8'))
        snapshots = master.get('snapshots', {})
        lines.append(f"CIVILIZATION STATE ({master.get('timestamp','')[:10]}) — {len(snapshots)} axes:")
        domains = {
            'HUMAN':        ['HUMAN_WELL_BEING_REVIEW','CULTURE_MEDIA_REVIEW','COGNITION_LEARNING_REVIEW','SOCIAL_RELATIONS_REVIEW','GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL'],
            'PLANET':       ['CLIMATE_GLOBAL_RISK_REVIEW','ENERGY_REVIEW','WATER_REVIEW','FOOD_REVIEW','MATERIALS_WASTE_REVIEW','ECOSYSTEMS_BIODIVERSITY_REVIEW','PLANETARY_POTENTIAL_REVIEW'],
            'CIVILIZATION': ['ECONOMY_WORK_REVIEW','INEQUALITY_POVERTY_REVIEW','INFRASTRUCTURE_CITIES_REVIEW','GOVERNANCE_INSTITUTIONS_REVIEW','EDUCATION_CULTURE_REVIEW','TECHNOLOGY_INFRA_REVIEW','TECHNOLOGY_AI_REVIEW'],
            'COSMOS':       ['LONG_TERM_FUTURE_REVIEW','SPACE_INFRASTRUCTURE_REVIEW','COSMIC_RESOURCES_REVIEW','DEEP_TIME_RISKS_REVIEW','GENERAL_SELF_REVIEW','GOAL_PROGRESS_REVIEW'],
        }
        for domain, axes in domains.items():
            lines.append(f'[ {domain} ]')
            for axis in axes:
                snap = snapshots.get(axis, {})
                raw = snap.get('raw', snap)
                metrics = raw.get('metrics', {})
                auto_lvls = _load_auto_levels()
                level = auto_lvls.get(axis) or snap.get('current_level', raw.get('current_level', '?'))
                quality = raw.get('data_quality', '')
                top = []
                for k, v in list(metrics.items())[:2]:
                    if v is not None:
                        try: top.append(f'{k}={round(float(v),1)}')
                        except: top.append(f'{k}={v}')
                metrics_str = ', '.join(top) if top else ''
                entry = f'  {axis}: {level}'
                if metrics_str: entry += f' | {metrics_str}'
                lines.append(entry)
            lines.append('')
    except Exception as e:
        lines.append(f'[snapshot unavailable: {e}]')
    try:
        trends = json.loads(TRENDS_PATH.read_text(encoding='utf-8'))
        imp = trends.get('improving', [])
        det = trends.get('deteriorating', [])
        if imp: lines.append(f"IMPROVING: {', '.join(imp)}")
        if det: lines.append(f"DETERIORATING: {', '.join(det)}")
    except Exception:
        pass
    return '\n'.join(lines)

@dataclass
class CortexCoreAgent:
    llm_call: LLMCall

    def build_prompt(self, user_msg: str) -> str:
        goal_ctx = goals.format_goal_context_short()
        civ_state  = _load_civilization_state()
        news_ctx   = _load_news_context()

        # Семантична памет — търси свързани спомени по въпроса
        mem_ctx = ""
        try:
            from memory.semantic_memory import query as mem_query
            memories = mem_query(user_msg, n=3)
            if memories:
                mem_ctx = "SEMANTIC MEMORY (relevant past insights):\n"
                for m in memories:
                    if m['relevance'] > 0.3:
                        mem_ctx += f"  [{m['axis']}] {m['text'][:120]}\n"
        except Exception:
            pass
        prompt = 'You are CORTEX++ AGI in service of one goal:\n'
        prompt += '"Sustainable civilization, dignity for all, AGI transparent and aligned."\n\n'
        prompt += 'CRITICAL RULES:\n'
        prompt += '- Use ONLY numbers and facts from the data provided below\n'
        prompt += '- NEVER invent statistics not present in the data\n'
        prompt += '- If you cite [AXIS_NAME], the number must come from that axis data\n'
        prompt += '- Respond in Bulgarian\n\n'
        prompt += 'GOAL STRUCTURE:\n' + goal_ctx + '\n\n'
        prompt += 'CURRENT CIVILIZATION STATE (real data):\n' + civ_state + '\n\n'
        prompt += 'LATEST INTERNET INTELLIGENCE:\n' + news_ctx + '\n\n'
        if mem_ctx:
            prompt += mem_ctx + '\n'
        prompt += 'INSTRUCTIONS:\n'
        prompt += '- Reason from the real data above.\n'
        prompt += '- Reference specific axes and metrics.\n'
        prompt += '- Prioritize DETERIORATING axes.\n'
        prompt += '- Cross-reference statistics with latest news and research.\n'
        prompt += '- Mention specific GitHub projects or scientific papers when relevant.\n'
        prompt += '- If YouTube transcripts reveal important insights, reference them.\n'
        prompt += '- Respond in Bulgarian.\n\n'
        prompt += 'User message:\n' + user_msg + '\n\nAssistant:'
        return prompt

    def run_once(self, user_msg: str) -> str:
        prompt = self.build_prompt(user_msg)
        return self.llm_call(prompt)

def main() -> None:
    agent = CortexCoreAgent(llm_call=llm_backend.call_internal_llm)
    print('CORTEX++ core agent (civilization-scale goal system).')
    print("Напиши съобщение (или 'exit' за край).")
    while True:
        try:
            user_msg = input('YOU> ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\n[EXIT]')
            break
        if not user_msg:
            continue
        if user_msg.lower() in {'exit', 'quit'}:
            print('[EXIT]')
            break
        try:
            reply = agent.run_once(user_msg)
        except Exception as e:
            print(f'[ERROR] {e}')
            continue
        print('AGENT>')
        print(reply)
        print('-' * 60)
        # Автоматично запази препоръката в ChromaDB
        try:
            import sys
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
            from memory.semantic_memory import remember
            remember(reply[:500], axis="ACTION_RECOMMENDATIONS", source="cortex_core_agent")
        except Exception as e:
            pass

if __name__ == '__main__':
    main()
