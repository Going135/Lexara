"""Validate untrusted model output against the actual OCR candidates."""
import math


def validate(payload, candidates, limit):
    if not isinstance(payload, dict) or not isinstance(payload.get('targets'), list):
        raise ValueError('Missing targets array')
    allowed = {c['lemma'].lower(): c for c in candidates}
    selected, seen = [], set()
    for target in payload['targets']:
        if not isinstance(target, dict):
            continue
        key = str(target.get('word', '')).lower()
        if key not in allowed or key in seen:
            continue
        priority = float(target.get('priority', 0))
        confidence = float(target.get('confidence', 0))
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (priority, confidence)):
            raise ValueError('Invalid confidence or priority')
        meaning = target.get('meaning')
        reason = target.get('reason')
        if not isinstance(meaning, str) or not meaning.strip() or not isinstance(reason, str):
            raise ValueError('Invalid explanation')
        item = dict(allowed[key])
        item.update(context_meaning=meaning[:500], ai_reason=reason[:500],
                    ai_confidence=confidence, ai_priority=priority,
                    collocations=[s[:120] for s in target.get('collocations', [])
                                  if isinstance(s, str)][:4])
        selected.append(item)
        seen.add(key)
    if not selected and candidates:
        raise ValueError('No valid OCR targets returned')
    selected.sort(key=lambda c: -c['ai_priority'])
    return selected[:limit]
