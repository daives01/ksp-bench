import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";

export interface MagneticPoint { id: string; x: number; y: number; label: string; ariaLabel: string; markerStyle?: CSSProperties; size?: number }
interface Body { x: number; y: number; vx: number; vy: number }
const PHYSICS = { tether: 3.5, halo: 67, capture: 66, spacing: 34, repulsion: .061, collision: .024, attraction: .14, spring: .09, damping: .66 };

export function MagneticPointField({ points, selectedId, onSelect, onActiveChange }: { points: MagneticPoint[]; selectedId: string | null; onSelect: (id: string) => void; onActiveChange: (id: string | null) => void }) {
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const fieldRef = useRef<HTMLDivElement>(null), pointRefs = useRef(new Map<string, HTMLDivElement>()), bodiesRef = useRef(new Map<string, Body>());
  const cursorRef = useRef({ x: 0, y: 0, inside: false }), focusedRef = useRef<string | null>(null), keyboardRef = useRef<string | null>(null), candidateRef = useRef<{ id: string; since: number } | null>(null);
  const activeCallbackRef = useRef(onActiveChange); activeCallbackRef.current = onActiveChange;

  useLayoutEffect(() => {
    let frame = 0, previous = performance.now();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const tick = (now: number) => {
      const bounds = fieldRef.current?.getBoundingClientRect();
      if (!bounds) { frame = requestAnimationFrame(tick); return; }
      const step = Math.min(1.6, (now - previous) / 16.67); previous = now;
      const bodies = bodiesRef.current, ids = new Set(points.map(({ id }) => id));
      for (const id of bodies.keys()) if (!ids.has(id)) bodies.delete(id);
      for (const point of points) if (!bodies.has(point.id)) bodies.set(point.id, { x: point.x / 100 * bounds.width, y: point.y / 100 * bounds.height, vx: 0, vy: 0 });
      const cursor = cursorRef.current;
      const distances = points.map(({ id }) => { const body = bodies.get(id)!; return { id, distance: Math.hypot(cursor.x-body.x,cursor.y-body.y) }; }).sort((a,b)=>a.distance-b.distance);
      const nearest=distances[0], currentDistance=distances.find(({id})=>id===focusedRef.current)?.distance??Infinity, keyboardId=keyboardRef.current;
      let next=focusedRef.current;
      if (keyboardId && ids.has(keyboardId)) next=keyboardId;
      else if (!cursor.inside || !nearest || nearest.distance>PHYSICS.capture) next=null;
      else if (next===null) next=nearest.id;
      else if (nearest.id!==next && (nearest.distance+8<currentDistance || currentDistance>48)) { if(candidateRef.current?.id!==nearest.id) candidateRef.current={id:nearest.id,since:now}; else if(now-candidateRef.current.since>=30) next=nearest.id; }
      else candidateRef.current=null;
      if(next!==focusedRef.current){ focusedRef.current=next; candidateRef.current=null; setFocusedId(next); activeCallbackRef.current(next); }
      const activeBody=next?bodies.get(next):undefined;
      const forces=points.map((point,index)=>{
        const body=bodies.get(point.id)!, anchorX=point.x/100*bounds.width, anchorY=point.y/100*bounds.height;
        let fx=(anchorX-body.x)*PHYSICS.spring, fy=(anchorY-body.y)*PHYSICS.spring;
        if(!reducedMotion&&!keyboardId&&cursor.inside&&point.id===next){ const dx=cursor.x-anchorX,dy=cursor.y-anchorY,d=Math.hypot(dx,dy),leash=d>PHYSICS.tether?PHYSICS.tether/d:1; fx+=(anchorX+dx*leash-body.x)*PHYSICS.attraction; fy+=(anchorY+dy*leash-body.y)*PHYSICS.attraction; }
        else if(!reducedMotion&&activeBody){ const dx=body.x-activeBody.x,dy=body.y-activeBody.y,d=Math.hypot(dx,dy); if(d<PHYSICS.halo){const angle=d<1?index*2.37:Math.atan2(dy,dx),strength=(PHYSICS.halo-d)*PHYSICS.repulsion;fx+=Math.cos(angle)*strength;fy+=Math.sin(angle)*strength;} }
        if(!reducedMotion) for(const other of points){ if(other.id===point.id)continue; const ob=bodies.get(other.id)!,dx=body.x-ob.x,dy=body.y-ob.y,d=Math.hypot(dx,dy);if(d<PHYSICS.spacing){const angle=d<1?index*2.37:Math.atan2(dy,dx),force=(PHYSICS.spacing-d)*PHYSICS.collision;fx+=Math.cos(angle)*force;fy+=Math.sin(angle)*force;} }
        return {fx,fy};
      });
      points.forEach((point,index)=>{const body=bodies.get(point.id)!,anchorX=point.x/100*bounds.width,anchorY=point.y/100*bounds.height,{fx,fy}=forces[index]!,inset=(point.size??15)/2+4;body.vx=reducedMotion?0:(body.vx+fx*step)*Math.pow(PHYSICS.damping,step);body.vy=reducedMotion?0:(body.vy+fy*step)*Math.pow(PHYSICS.damping,step);body.x=reducedMotion?anchorX:body.x+body.vx*step;body.y=reducedMotion?anchorY:body.y+body.vy*step;body.x=Math.max(inset,Math.min(bounds.width-inset,body.x));body.y=Math.max(inset,Math.min(bounds.height-inset,body.y));pointRefs.current.get(point.id)?.style.setProperty("transform",`translate3d(${body.x}px, ${body.y}px, 0)`);});
      frame=requestAnimationFrame(tick);
    };
    frame=requestAnimationFrame(tick); return()=>cancelAnimationFrame(frame);
  },[points]);

  return <div ref={fieldRef} className="magnetic-field" onPointerMove={(event)=>{const bounds=fieldRef.current?.getBoundingClientRect();if(bounds)cursorRef.current={x:event.clientX-bounds.left,y:event.clientY-bounds.top,inside:true};}} onPointerLeave={()=>{cursorRef.current.inside=false;if(!keyboardRef.current)activeCallbackRef.current(null);}}>{points.map((point)=>{const focused=focusedId===point.id,size=point.size??15,horizontal=point.x<22?"is-left":point.x>78?"is-right":"is-center",vertical=point.y<22?"is-below":"is-above";return <div key={point.id} ref={(node)=>{if(node)pointRefs.current.set(point.id,node);else pointRefs.current.delete(point.id);}} className={`magnetic-point ${focused?"is-focused":""}`}>{focused?<span className={`magnetic-point__label ${horizontal} ${vertical}`}>{point.label}</span>:null}<button type="button" data-model-selection aria-label={point.ariaLabel} aria-pressed={selectedId===point.id} onClick={()=>onSelect(point.id)} onFocus={(event)=>{if(event.currentTarget.matches(":focus-visible")){keyboardRef.current=point.id;focusedRef.current=point.id;setFocusedId(point.id);activeCallbackRef.current(point.id);}}} onBlur={()=>{if(keyboardRef.current===point.id)keyboardRef.current=null;if(!cursorRef.current.inside){focusedRef.current=null;setFocusedId(null);activeCallbackRef.current(null);}}} style={{width:size,height:size,...point.markerStyle}}/></div>;})}</div>;
}
