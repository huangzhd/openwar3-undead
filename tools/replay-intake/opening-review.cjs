const {createHash}=require('node:crypto');

function digest(values) {
  return createHash('sha256').update(JSON.stringify(values)).digest('hex');
}

// Called only with the inventory newly decoded from the local W3G.
function openingReview(report, notes) {
  const {opening}=report.commands;
  const sourceHash=digest(Object.entries(report.source).sort(([a],[b])=>a<b?-1:a>b?1:0));
  const rows=opening.orders.map(order=>{
    const signals=[];
    if (order.prior_observed_exact_point!==null) signals.push('previous_order_at_same_site');
    const previous=opening.orders[order.prior_observed_same_code-1];
    if (previous && previous.recorded_point.some((v,i)=>v!==order.recorded_point[i]))
      signals.push('different_site_from_previous_same_building');
    if (!order.prior_subgroup) signals.push('no_typed_subgroup');
    else if (order.prior_subgroup.type!=='uaco') signals.push('prior_subgroup_not_acolyte');
    const id=digest(['opening-review-v1',report.sha256,sourceHash,opening.player_id,order]);
    return {id,order,signals,annotation:null};
  });
  if (notes!==undefined) {
    if (!Array.isArray(notes) || notes.length>rows.length) throw new Error('invalid_review_notes');
    const byId=new Map(rows.map(row=>[row.id,row]));
    for (const note of notes) {
      if (!note || Object.keys(note).sort().join(',')!=='comment,id,verdict' ||
          !['tactical_review_candidate','possible_reissue_or_correction','undetermined'].includes(note.verdict) ||
          typeof note.comment!=='string' || !note.comment.trim() || note.comment.length>1000)
        throw new Error('invalid_review_annotation');
      const row=byId.get(note.id);
      if (!row || row.annotation) throw new Error('unmatched_or_duplicate_review_order');
      if (report.source.kind==='format_fixture' && note.verdict==='tactical_review_candidate')
        throw new Error('fixture_is_for_format_review_only');
      row.annotation={verdict:note.verdict,comment:note.comment.trim()};
    }
  }
  const {orders,...coverage}=opening;
  return {schema:'dayuan-opening-review-v1',sha256:report.sha256,source:report.source,
    source_sha256:sourceHash,player_id:opening.player_id,coverage,rows,
    professional_identity:report.professional_identity,player_view_reconstructed:false,
    engine_effects_verified:false,training_labels:0,positive_demonstrations_approved:false};
}

module.exports={openingReview};
