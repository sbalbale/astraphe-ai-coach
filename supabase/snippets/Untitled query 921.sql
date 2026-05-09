select analysis_type, scope_key, updated_at, model
from public.athlete_analyses
where analysis_type='workout'
order by updated_at desc
limit 20;