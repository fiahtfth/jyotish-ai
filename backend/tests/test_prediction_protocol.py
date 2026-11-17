from datetime import date, datetime
import json
from copy import deepcopy
from app.astro import prediction as Q, sensitivity as S
from app.astro.validation import evaluate_dataset
from tests.test_precision import make_facts


def analysis():
    return {'domain':'career', 'analysis_window':{'start':'2027-01-01','end':'2027-12-31'},
            'support_count':3,'conflict_count':0,'unavailable_count':0,
            'precision':{'confirmation':'Mostly aligned','yogini':'support','sudarshana':'neutral'},
            'sensitivity':{'verdict_stable':True,'timing_stable':True}}


def test_decisions_require_specific_event_and_stable_conflict_free_support():
    a = analysis()
    assert Q.decide('Will I get a promotion?', a)['disposition'] == 'event_indicated'
    assert Q.decide('How is my career?', a)['disposition'] == 'abstain'
    a['conflict_count'] = 1
    assert Q.decide('Will I get a promotion?', a)['disposition'] == 'abstain'
    a['conflict_count'] = 0
    a['sensitivity']['timing_stable'] = False
    assert Q.decide('Will I get a promotion?', a)['disposition'] == 'abstain'


def test_birth_time_samples_cross_midnight_and_do_not_mutate_input(monkeypatch):
    b, f = make_facts('approximate')
    b.hour, b.minute = 0, 10
    before = deepcopy(b)
    captured = []
    def compute(c):
        captured.append(datetime(c.year,c.month,c.day,c.hour,c.minute))
        return f
    monkeypatch.setattr(S.engine, 'compute', compute)
    monkeypatch.setattr(S.pillars, 'evaluate', lambda *a: {'pillars':{'parashari':'support'},'unavailable_count':0})
    monkeypatch.setattr(S.precision, 'timing_windows', lambda *a: {'windows':[],'status':'applied'})
    r = S.evaluate(f,b,'career',date(2027,1,1),date(2027,12,31),False)
    assert b == before
    assert datetime(1990,5,14,23,10) in captured
    assert len(r['samples']) == 5 and r['status'] == 'sampled_stable'


def test_changed_or_failed_sample_blocks_stability(monkeypatch):
    b, f = make_facts('unknown')
    monkeypatch.setattr(S.engine, 'compute', lambda c: f)
    count = [0]
    def core(*a):
        count[0] += 1
        return {'pillars':{'parashari':'support' if count[0] == 1 else 'neutral'},'unavailable_count':0}
    monkeypatch.setattr(S.pillars,'evaluate',core)
    monkeypatch.setattr(S.precision,'timing_windows',lambda *a:{'windows':[]})
    r = S.evaluate(f,b,'career',date(2027,1,1),date(2027,12,31),False)
    assert not r['verdict_stable'] and r['status'] == 'sensitive'
    monkeypatch.setattr(S.engine,'compute',lambda c: (_ for _ in ()).throw(ValueError('failed')))
    r = S.evaluate(f,b,'career',date(2027,1,1),date(2027,12,31),False)
    assert r['status'] == 'incomplete' and r['errors']


def row(outcome, **kw):
    return dict({'profile_id':1,'domain':'career','event_type':'promotion','forecast':'event_indicated','protocol':Q.VERSION,
                 'success_criteria':'Formal promotion','created_at':'2026-12-01T12:00:00',
                 'window_start':'2027-01-01','window_end':'2027-02-01','outcome':outcome,'outcome_at':'2027-02-05'}, **kw)


def test_scorecard_never_credits_partial_unanswered_legacy_or_retrospective():
    rows = [row('happened'),row('did_not'),row('outside_window'),row('partly'),row(None),row('unsure'),
            row('happened',forecast='abstain'),row('happened',protocol=None),row('happened',created_at='2027-01-10')]
    for i, item in enumerate(rows):
        item['profile_id'] = i + 1
    r = Q.scorecard(rows, today=date(2027,3,1))
    assert (r['hits'],r['misses'],r['scored'],r['partial'],r['unresolved']) == (1,2,3,1,2)
    assert r['abstentions'] == 1 and r['total_analyses'] == 9
    assert Q.scorecard(rows,today=date(2027,1,15))['scored'] == 0


def test_ai_cannot_override_abstention_or_add_a_new_date():
    a = analysis();a['decision'] = Q.decide('How is my career?',a)
    assert 'guaranteed' not in Q.constrain_reply('You are guaranteed a promotion.',a)
    a['decision'] = Q.decide('Will I get a promotion?',a)
    assert '2029-01-01' not in Q.constrain_reply('It happens 2029-01-01.',a)
    assert 'confirmed' not in Q.constrain_reply('Your promotion is confirmed.',a)


def test_model_receives_complete_precision_json(monkeypatch):
    from app.llm import providers as P
    monkeypatch.setattr(P.settings,'LLM_PROVIDER','groq')
    monkeypatch.setattr(P.settings,'GROQ_API_KEY','test')
    monkeypatch.setattr(P.settings,'LLM_EXTERNAL_CONSENT',True)
    payload = {'evidence':'x'*6000,'precision':{'last_layer':'must_reach_the_model'}}
    seen=[]
    def fake(system,messages,timeout):
        seen.append(system);return 'OK'
    monkeypatch.setitem(P.PROVIDERS,'groq',fake)
    P.generate([{'role':'user','content':'test'}],analysis=payload)
    assert 'must_reach_the_model' in seen[0]
    assert json.loads(seen[0].split('current question):\n')[1]) == payload


def test_validation_prevents_person_and_future_outcome_leakage():
    rows=[row('happened',profile_id=1,window_start='2026-01-01',window_end='2026-02-01',created_at='2025-12-01',outcome_at='2026-02-05'),
          row('did_not',profile_id=2,window_start='2026-01-01',window_end='2026-02-01',created_at='2025-12-01',outcome_at='2026-02-05'),
          row('did_not',profile_id=3,window_start='2026-01-01',window_end='2026-02-01',created_at='2025-12-01',outcome_at='2028-02-05'),
          row('happened',profile_id=2,created_at='2027-01-01',window_start='2027-01-02')]
    r=evaluate_dataset(rows,cutoff='2027-01-01',holdout_profiles=[2],today=date(2027,3,1))
    assert r['development_rows'] == 1 and r['holdout_rows'] == 1
    assert r['by_domain']['career:promotion']['development_event_frequency'] == 1


def test_duplicate_forecasts_do_not_multiply_hits():
    r = Q.scorecard([row('happened'), row('happened')],today=date(2027,3,1))
    assert r['hits'] == 1 and r['duplicate_forecasts_excluded'] == 1
    assert r['observed_hit_rate_wilson95'][0] < 0.3


def test_past_intervals_are_never_issued_as_future_forecasts():
    a=analysis()
    a['analysis_window']={'start':'2000-01-01','end':'2000-12-31'}
    assert Q.decide('Will I get a promotion?',a)['disposition'] == 'abstain'
