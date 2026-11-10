"""Reference-first Unity brief; unsupported categories never fall back to a corridor."""
import json,time
from backend.models.schema import UnityBlueprint
from backend.integrations.process import contained,checksum
from backend.orchestration.versions import Versions

CAPABILITIES='''The renderer supports a generic declarative custom_scene for any representable reference category, in addition to legacy subway_car/enclosed_corridor presets. custom_scene is assembled from named opaque materials and box/sphere/cylinder/capsule/quad procedural bare_tree and bounded custom mesh primitives with position, scale, rotation, repeated grids, small position jitter and alternate-material probability; Unity primitives use unit box/sphere/quad size and cylinders/capsules of height 2 before scaling. Repeat grids use count [x,y,z] and step [dx,dy,dz] in world axes (rotation affects each part, not the grid). There are up to 400 object groups / 6000 instances (each bare_tree counts as 32), 64 materials and 32 point/spot/directional lights. Materials support RGB, roughness, metallic, emission, procedural plaster/concrete/brick/wood/metal/fabric/snow/asphalt/bark/panel detail. Environment includes sky/ambient/fog RGB, fog density, optional snow/rain/dust particles, weather_size_multiplier, weather_speed_multiplier and weather_wind, and light_gain scales ambient, emissive and light intensities. Each material has detail_strength and each light has shadow_strength. Use these controls to match brightness, weather and shadow contrast without washing out important detail. A mesh object supplies vertices as {x,y,z} within -0.5..0.5 and a flat triangles array of zero-based indices, with correct winding; up to 256 vertices and 512 triangles per group, 12000 vertices across groups. Mesh is transformed by position, scale and rotation, with planar UVs. Use meshes for distinctive roofs, terrain or props when primitives are insufficient. No arbitrary code, asset downloading, exact photographic textures, unbounded meshes, animated people or automatic photorealistic reconstruction. Use custom_scene for outdoor/urban/natural/architectural scenes rather than forcing them into a legacy interior. bare_tree is a branching leafless tree: scale is width, height and depth, position is its centre. Use bark material and vary rotations/scales. Describe how visible structures/vegetation/props can be decomposed into supported geometry; explicitly list what remains approximate or unsupported. If essential content cannot be represented use unsupported instead of inventing renderer capabilities. Camera coordinates are meters (500m scene bounds), Y is height, yaw 0 faces +Z, positive pitch looks down.'''

class ScenePlanning:
    def __init__(self,engine):self.engine=engine
    async def generate(self,e):
        engine=self.engine;root=engine.directory(e)
        if not engine.settings.vision_enabled:raise ValueError('Enable image-capable agent support in Settings before preparing a reference-based Unity prompt')
        config=engine.store.config(e); selected=config.get('unity_reference_image')
        refs=[selected] if selected else json.loads((root/'references.json').read_text())
        if selected and checksum(contained(root,selected))!=config.get('unity_reference_checksum'):raise ValueError('Selected image changed; choose it again before planning')
        if not refs:raise ValueError('Add a visual reference before preparing Unity')
        for name in refs:
            if not contained(root,name).is_file():raise ValueError('Visual reference is missing')
        prompt=('Before any Unity project creation or scene setup, inspect the actual pixels of every source image: '+json.dumps(refs)+'. Read visual_reference.json and the episode direction. Write a comprehensive Unity scene-building prompt for another agent, NOT a generic style summary. Do not create a Unity project, execute code, render, or modify anything except the required JSON. If you cannot view the images, fail explicitly. Distinguish observed details from estimates/occluded areas. '+CAPABILITIES+
                ' Describe foreground/midground/background, dimensions and relative placement, number and rhythm of buildings/doors/windows, facade breaks and balconies, terrain/props/vegetation, material roughness and scale/weathering, texture detail, light sources with approximate colors/intensities/shadows, sky/fog/depth, elevated versus eye-level viewpoint, horizon, lens/FOV/roll and framing, weather particle scale/direction/motion and restrained camera motion. Match the actual reference category and viewpoint; for example an outdoor view must not become an indoor corridor. This workflow must work across different references, not hard-code a snowy courtyard. Include explicit must-have and must-not-substitute rules. State unsupported fidelity requirements honestly. The implementation_prompt must be a detailed self-contained instruction, incorporating all sections and an actionable setup sequence. Provide at least six observable fidelity checks, including scene category, composition, material detail, light distribution, spatial depth and atmosphere. Explain why each major choice follows the image. Do not claim photorealism or a visual match before rendering. Use plain language in the user-facing prompt.')
        if selected:prompt+=' The selected edited image is the authoritative reference. Inspect it directly; earlier source images and visual_reference.json are historical context only if they disagree. Read the existing scene_spec.json and plan changes to the current Unity scene, preserving details not contradicted by the selected image. Do not copy the reference as the rendered result.'
        result=await engine.ask(e,'unity_blueprint',prompt,UnityBlueprint)
        plan=UnityBlueprint.model_validate(result['result']).model_dump()
        if selected and checksum(contained(root,selected))!=config.get('unity_reference_checksum'):raise ValueError('Selected image changed during planning')
        text='# Unity scene implementation prompt\n\n'+plan['implementation_prompt']+'\n\n## Fidelity checks\n\n'+'\n'.join('- '+x for x in plan['fidelity_checks'])+'\n\n## Limits and uncertainties\n\n'+'\n'.join('- '+x for x in plan['limitations'])+'\n'
        (root/'unity_blueprint.md').write_text(text)
        return {**result,'artifacts':list(dict.fromkeys([*result['artifacts'],'unity_blueprint.md','visual_reference.json','references.json',*refs]))}
    async def enable(self,e,feedback='',reference_image=None):
        engine=self.engine;store=engine.store;engine.revisions.assert_editable(e)
        if store.task(e,'visual_reference')['status']!='Completed':raise ValueError('Finish visual reference analysis first')
        config=store.config(e);updated={**config,'unity_planning_enabled':True}
        if reference_image is not None:
            path=contained(engine.directory(e),reference_image)
            if not path.is_file():raise ValueError('Selected image is missing')
            updated.update(unity_reference_image=reference_image,unity_reference_checksum=checksum(path))
        from backend.orchestration.workflow import workflow
        graph=workflow(updated);affected={'unity_blueprint','unity_preview'}
        while True:
            extra={n for n,deps in graph.items() if set(deps)&affected}-affected
            if not extra:break
            affected|=extra
        if any((e,n) in engine.running and not engine.running[(e,n)].done() for n in affected):raise ValueError('Stop the active visual/final tasks before preparing a new Unity prompt')
        if any(r['status'] in {'Planning','Applying','Waiting for quota','Waiting for CLI','Waiting for Permission'} for r in engine.revisions.rows(e)):raise ValueError('Finish the active revision first')
        existing={r['name'] for r in store.rows('SELECT name FROM tasks WHERE episode=?',(e,))}
        version=Versions(store,engine.root).archive(e,affected&existing)
        try:
            store.db.execute('BEGIN IMMEDIATE');Versions(store,engine.root).insert(version)
            store.db.execute('INSERT OR IGNORE INTO tasks(episode,name) VALUES(?,?)',(e,'unity_blueprint'))
            for n in affected:
                state={'feedback':feedback.strip()} if n=='unity_blueprint' else {}
                store.db.execute("UPDATE tasks SET status='Pending',data=?,error='',started=NULL,finished=NULL WHERE episode=? AND name=?",(json.dumps(state),e,n))
            store.db.execute('UPDATE episodes SET config=? WHERE id=?',(json.dumps(updated),e))
            store.db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',('started:'+e,'true',time.time()));store.db.commit()
        except BaseException:store.db.rollback();raise
        store.log(e,'unity_blueprint','Detailed Unity prompt requested; only visual descendants and final assembly were invalidated.');engine.wake.set()
