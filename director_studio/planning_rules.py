"""Persistent reference-budget instructions supplied to the local writing model."""
import re
RULES = """REFERENCE BUDGET AND CONTINUITY RULES:
- A named figure does not automatically need a character asset or an identity reference.
- Keep protagonists, recurring cast, identity-critical visible faces and pivotal speaking characters as persistent characters. Reuse their saved identities.
- Anonymous extras, indistinct guards, silhouettes, brief incidental figures, and motionless/dead bodies with concealed faces that only support one or two shots are prompt-only scene details. Describe clothing, pose and placement directly in the relevant shot. Do not make portrait, turnaround, expression or training jobs for them.
- A dead person who returns in flashbacks or needs a recognizable recurring identity is an exception and may need a persistent character.
- Set reference_policy to persistent or prompt_only when extracting characters. Do not omit incidental figures from the story or shot prompts.
- Default a one-off background to view_policy single: one master reference is sufficient. Do not build a seven-angle pack merely because a location exists. Additional images already supplied by the user are usable without regeneration.
- Use view_policy multi only when recurring locations or explicit camera/continuity needs justify additional reference renders. Generate only needed angles, always from the same master.
- Keep user-supplied references authoritative. Never overwrite them, invent a different face, or silently add extra reference generation.
"""

def incidental(row):
 if row.get('reference_policy')=='persistent':return False
 if row.get('reference_policy')=='prompt_only':return True
 text=row.get('description',row.get('text','')).lower()
 if re.search(r'\b(recurring|flashback|recognizable identity|identity critical)\b',text):return False
 return bool(re.search(r'\b(dead|corpse|deceased|motionless)\b',text) and re.search(r'face.{0,30}(hidden|conceal)|anonymous|unidentifiable',text))

def retire(state,aid):
 asset=state['nodes'][aid];state.setdefault('asset_policy_overrides',{})[re.sub(r'[^\w]+',' ',asset['title'].casefold()).strip()]='prompt_only';asset.update(archived=True,reference_policy='prompt_only',archive_reason='Incidental scene detail; no separate identity reference required')
 refs={n['id'] for n in state['nodes'].values() if n.get('parent')==aid and n['kind']=='reference'}
 for rid in refs:state['nodes'][rid].update(archived=True,archive_reason='Prompt-only incidental figure')
 for n in state['nodes'].values():
  links=n.get('asset_links',{})
  if aid in links.get('characters',[]):
   n.setdefault('incidental_figures',{})[asset['title']]=asset['text'];links['characters']=[x for x in links['characters'] if x!=aid]
  n['references']=[x for x in n.get('references',[]) if x not in refs]
  if 'cast' in n.get('production',{}):n['production']['cast']=[x for x in n['production']['cast'] if x.get('character')!=aid]
  if 'characters' in n.get('production',{}):n['production']['characters']=[x for x in n['production']['characters'] if x!=aid]
