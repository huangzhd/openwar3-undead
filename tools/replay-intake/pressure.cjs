// Order evidence only. Earlier subgroup type hints do not prove current vision or actor.
const {createHash}=require('node:crypto');
function pressureCollector(player,sha) {
  const types=new Map();
  const report={schema:'dayuan-human-pressure-orders-v1',player_id:player,
    target_window_ms:[120000,480000],production_orders:[],typed_target_orders:[],unit_type_hints:[],
    gaps:[],undecoded_blocks:0,omitted:{production:0,targets:0,hints:0,gaps:0},
    unknown_target_orders:0,other_typed_target_orders:0,player_view_reconstructed:false,engine_effects_verified:false,training_labels:0};
  const objectKey=o=>Array.isArray(o)&&o.length===2&&o.every(n=>Number.isInteger(n)&&n>=0&&n<=0xffffffff)
    &&!o.every(n=>n===0xffffffff)?JSON.stringify(o):null;
  const objectId=o=>createHash('sha256').update(JSON.stringify([sha,player,o])).digest('hex');
  function push(key,count,row) {if(report[key].length<512)report[key].push(row);else report.omitted[count]++;}
  return {report,
    gap(where) {types.clear();report.undecoded_blocks++;push('gaps','gaps',where);},
    action(a,where) {
      const key=objectKey(a.object);
      if(a.id===0x19 && key && a.itemId?.length===4) {
        const type=Buffer.from(a.itemId).reverse().toString('latin1');
        if(!/^[A-Za-z0-9]{4}$/.test(type))return;
        const hint={...where,type,replay_object_id:objectId(a.object)};
        types.set(key,hint);
        if(['Ulic','uobs','uslh'].includes(type))push('unit_type_hints','hints',hint);
      }
      if(a.orderId?.length!==4)return;
      const code=Buffer.from(a.orderId).reverse().toString('latin1');
      const point=Array.isArray(a.target)&&a.target.length===2&&a.target.every(Number.isFinite)?a.target:null;
      if(a.id===0x11 && code==='uslh' && point || a.id===0x10 && ['Ulic','uobs','ucry','unp1','unp2'].includes(code))
        push('production_orders','production',{...where,action_id:a.id,code,flags:a.abilityFlags,
          point:a.id===0x11?point:null,issue_actor_confirmed:false});
      if(a.id!==0x12 || !key || where.timeslot_ms<120000 || where.timeslot_ms>480000)return;
      const hint=types.get(key);
      if(!hint){report.unknown_target_orders++;return;}
      if(!['Hamg','hpea','hmil'].includes(hint.type) && !/^n[A-Za-z0-9]{3}$/.test(hint.type)) {
        report.other_typed_target_orders++;return;
      }
      push('typed_target_orders','targets',{...where,action_id:a.id,order:Buffer.from(a.orderId).readUInt32LE(),
        flags:a.abilityFlags,point,replay_object_id:objectId(a.object),prior_type_hint:hint,
        hint_age_ms:where.timeslot_ms-hint.timeslot_ms,issue_actor_confirmed:false});
    }
  };
}
module.exports={pressureCollector};
