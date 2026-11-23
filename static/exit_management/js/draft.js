/* draft.js - read the form into a payload, fill it from a saved draft/submission, and Save Draft. */
const ExDraft = {
  /** Current form values as the API payload. Employee identity is NOT included - the server supplies it. */
  collect() {
    const radio = name => { const r = document.querySelector(`input[name="${name}"]:checked`); return r ? r.value : null; };
    const text = id => document.getElementById(id).value.trim();
    const ratings = (list, prefix) => Object.fromEntries(list.map(([k]) => [k, radio(prefix + k)]));
    const keys = ['systems_and_processes', 'team_experience', 'resignation_reason', 'new_employer', 'pull_factors', 'recommend_reason',
                  'jhs_memories', 'improvements', 'employee_benefits', 'departure_prevention'];
    const ei = Object.fromEntries(keys.map(k => [k, text('ei_' + k)]));
    ei.would_rejoin = radio('ei_would_rejoin');
    ei.better_prospect = radio('ei_better_prospect');
    ei.recommend_company = radio('ei_recommend_company');
    return {
      resignation_date: document.getElementById('f_resignation').value,
      last_working_date: document.getElementById('f_lastday').value,
      manager_feedback: ratings(EX.MANAGER, 'rm_'),
      company_feedback: ratings(EX.COMPANY, 'rc_'),
      exit_interview: ei,
    };
  },

  /** Fill the form from a stored document (draft or submitted). */
  apply(form) {
    if (!form) return;
    const det = form.employee_details || {};
    document.getElementById('f_resignation').value = det.resignation_date || '';
    document.getElementById('f_lastday').value = det.last_working_date || '';
    const check = (name, value) => {
      if (!value) return;
      const el = document.querySelector(`input[name="${name}"][value="${value}"]`);
      if (el) el.checked = true;
    };
    Object.entries(form.manager_feedback || {}).forEach(([k, v]) => check('rm_' + k, v));
    Object.entries(form.company_feedback || {}).forEach(([k, v]) => check('rc_' + k, v));
    const ei = form.exit_interview || {};
    Object.entries(ei).forEach(([k, v]) => {
      const el = document.getElementById('ei_' + k);
      if (el) el.value = v || '';
    });
    ['would_rejoin', 'better_prospect', 'recommend_company'].forEach(k => check('ei_' + k, ei[k]));
    ExSignature.load(form.signature_file);
  },

  /** POST the (possibly incomplete) form as a draft. */
  async save() {
    return ExApi.call('/draft', 'POST', this.collect());
  },
};
