/* validation.js - the form's question lists (keys match the backend schema) and the browser-side checks.
   The server repeats every check; this only gives the employee quick feedback. */
const EX = {
  MANAGER: [
    ['team_management', 'Team Management'], ['communication', 'Communication'], ['motivation', 'Motivation'],
    ['technical_skills', 'Technical Skills'], ['fairness', 'Fairness'], ['approachability', 'Approachability'],
    ['relationship_with_other_teams', 'Relationship with other teams'], ['management_skills', 'Management Skills'],
  ],
  COMPANY: [
    ['company_culture', 'Company Culture'], ['learning_experience', 'Learning experience'],
    ['rewards_recognition', 'Rewards & Recognition'], ['performance_review_system', 'Performance Review System'],
    ['physical_working_conditions', 'Physical working conditions'], ['facilities', 'Facilities'],
    ['opportunity_for_growth', 'Opportunity for growth'], ['management_skills', 'Management Skills'],
  ],
  RATINGS: ['Good', 'Satisfactory', 'Poor'],
  // [key, "Q number. short label"] - Q22 and the employer name are conditional
  INTERVIEW: [
    ['would_rejoin', '17. Would you rejoin JHS'], ['systems_and_processes', '18. Systems and processes'],
    ['team_experience', '19. Working in your team'], ['resignation_reason', '20. Reason for resignation'],
    ['better_prospect', '21. Better prospect (Yes/No)'], ['recommend_company', '23. Recommend the company'],
    ['jhs_memories', '24. Three things you would remember'], ['improvements', '25. Three things that would have made life better'],
    ['employee_benefits', '26. Employee benefits'], ['departure_prevention', '27. What would have prevented your departure'],
  ],
};

const ExValidation = {
  clearMarks() {
    document.querySelectorAll('.row-error').forEach(el => el.classList.remove('row-error'));
  },
  mark(el) { if (el) el.classList.add('row-error'); },

  /** The two dates the employee must enter. */
  dates(data) {
    const errors = [];
    if (!data.resignation_date) errors.push('Resignation Date is required');
    if (!data.last_working_date) errors.push('Last Working Date is required');
    if (data.resignation_date && data.last_working_date && data.last_working_date < data.resignation_date) {
      errors.push('Last Working Date cannot be before the Resignation Date');
    }
    return errors;
  },

  /** 16 ratings, the interview answers and the uploaded signature. Marks missing rows red. */
  answers(data) {
    const errors = [];
    EX.MANAGER.forEach(([k, label]) => {
      if (!data.manager_feedback[k]) { errors.push(`About Reporting Manager - rate "${label}"`); this.mark(document.getElementById('rm_' + k)); }
    });
    EX.COMPANY.forEach(([k, label]) => {
      if (!data.company_feedback[k]) { errors.push(`About JHS - rate "${label}"`); this.mark(document.getElementById('rc_' + k)); }
    });
    const ei = data.exit_interview;
    EX.INTERVIEW.forEach(([k, label]) => {
      if (!ei[k]) { errors.push(`Question "${label}" is required`); this.mark(document.querySelector(`[data-q="${k}"]`)); }
    });
    if (ei.recommend_company === 'No' && !ei.recommend_reason) { errors.push('Please tell us why you would not recommend the company (Q23)'); this.mark(document.getElementById('recommendWrap')); }
    if (ei.better_prospect === 'Yes') {
      if (!ei.new_employer) { errors.push('Please mention the name of your new employer (Q21)'); this.mark(document.getElementById('employerWrap')); }
      if (!ei.pull_factors) { errors.push('Question "22. Pull factors of your new employer" is required'); this.mark(document.getElementById('pullWrap')); }
    }
    if (ExSignature.busy) { errors.push('Please wait for the signature upload to finish'); this.mark(document.getElementById('sigCard')); }
    else if (!ExSignature.current) { errors.push('Please upload your signature document'); this.mark(document.getElementById('sigCard')); }
    return errors;
  },
};
