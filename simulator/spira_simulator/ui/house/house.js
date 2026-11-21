import * as THREE from "./three.module.min.js";

export const TV_SCENES = { kids_party: "어린이 파티", party: "파티", calm: "차분한 분위기", cinema: "영화" };
const OVERVIEW = { eye: [8.5, 10.6, 17.4], aim: [-0.10, 0.76, 0], zoom: 1 };
const WARM_WHITE = new THREE.Color("#ffa85f");
const NEUTRAL_WHITE = new THREE.Color("#ffd8b7");
const COOL_WHITE = new THREE.Color("#fff9fb");
const LAMP_SHADE = new THREE.Color("#ffe4b4");

export function hsvColor({ hue, saturation, brightness } = {}) {
  if (![hue, saturation, brightness].every(Number.isFinite)) return null;
  const value = brightness / 100;
  const chroma = value * saturation / 100;
  const segment = ((hue % 360 + 360) % 360) / 60;
  const offset = chroma * (1 - Math.abs(segment % 2 - 1));
  const colors = [[chroma, offset, 0], [offset, chroma, 0], [0, chroma, offset],
    [0, offset, chroma], [offset, 0, chroma], [chroma, 0, offset]];
  return "#" + colors[Math.floor(segment)]
    .map((channel) => Math.round((channel + value - chroma) * 255).toString(16).padStart(2, "0"))
    .join("");
}

export function createLivingLight(lamp, source, glowLevel) {
  const fromTint = lamp.color.clone();
  const targetTint = lamp.color.clone();
  let fromLevel = 0, targetLevel = 0, changedAt = 0;

  return {
    update({ power, color }, now) {
      fromTint.copy(lamp.color);
      targetTint.copy(fromTint);
      fromLevel = glowLevel.value;
      changedAt = now;
      targetLevel = 0;
      if (power !== true || !color) return false;

      const tint = hsvColor({ ...color, brightness: 100 });
      if (tint && Number.isFinite(color.brightness)) {
        targetTint.set(tint);
        targetLevel = THREE.MathUtils.clamp(color.brightness / 100, 0, 1);
        return targetLevel > 0;
      }
      if (Number.isFinite(color.kelvin)) {
        const kelvin = THREE.MathUtils.clamp(color.kelvin, 2700, 6500);
        if (kelvin < 4000) targetTint.lerpColors(WARM_WHITE, NEUTRAL_WHITE, (kelvin - 2700) / 1300);
        else targetTint.lerpColors(NEUTRAL_WHITE, COOL_WHITE, (kelvin - 4000) / 2500);
        // The temperature reading carries no brightness.
        targetLevel = .26;
      }
      return false;
    },
    render(now, instant = false) {
      const mix = instant ? 1 : THREE.MathUtils.smoothstep(now - changedAt, 0, 1000);
      const level = THREE.MathUtils.lerp(fromLevel, targetLevel, mix);
      lamp.color.lerpColors(fromTint, targetTint, mix);
      lamp.intensity = 84 * level;
      source.color.copy(LAMP_SHADE).lerp(lamp.color, level);
      source.emissive.copy(lamp.color);
      source.emissiveIntensity = 2.4 * level;
      glowLevel.value = level;
    },
  };
}

const TV_LOOKS = {
  kids_party: { sky: ["#9669bd", "#e997ac"], spill: ["#ffb47f", "#db8fde"] },
  party: { sky: ["#5a204b", "#c35777"], spill: ["#fba46d", "#ec679e"] },
  calm: { sky: ["#314f5e", "#b3cdab"], spill: ["#66a29c", "#b3cdab"] },
  cinema: { sky: ["#13162d", "#545b93"], spill: ["#7776ba", "#a0a7ef"] },
};

const TV_SCREEN = { width: 2.12, height: 1.16, center: [-.70, 1.52, -3.419] };
const PENDANT = [-1.42, 2.73, -.23];
const LABEL_ANCHORS = {
  cleaner_01: [.82, .52, -2.50], light_01: [-1.42, 2.51, -.23], display_01: [-.70, 2.17, -3.41],
  cooktop_01: [2.28, 1.43, -2.79], oven_01: [3.74, 1.00, -2.40],
  fridge_01: [6.13, 2.14, -2.55], plug_kettle: [5.25, 1.72, -3.00],
  purifier_01: [-3.95, .84, -2.16], styler_01: [-6.14, 2.14, .88],
  speaker_01: [-2.46, .91, -2.95], entrance: [-5.45, 1.14, -2.48],
};

export function orientHouseCamera(camera, eye, aim, zoom, viewport) {
  const extent = Math.max(5.35, 7.56 / viewport) / zoom;
  Object.assign(camera, { left: -extent * viewport, right: extent * viewport,
    top: extent, bottom: -extent, near: .1, far: 100 });
  camera.updateProjectionMatrix();
  camera.position.copy(eye);
  camera.lookAt(aim);
  camera.updateMatrixWorld();
}

// The foundation and the top of the cutaway walls define the visible silhouette.
const HOUSE_OUTLINE = [
  ...[-6.8, 6.8].flatMap(x => [-.43, .03].flatMap(y => [-3.975, 3.975].map(z => [x, y, z]))),
  [-6.72, 2.73, -3.96], [6.72, 2.73, -3.96], [-6.72, 2.73, -1.63],
].map(position => new THREE.Vector3(...position));

export function fitViewerCamera(camera, width, height) {
  const compact = width < 720;
  const sides = compact ? 10 : width * .045;
  const top = compact ? 42 : 54;
  const bottom = compact ? 36 : 24;
  const bounds = new THREE.Box3().setFromPoints(
    HOUSE_OUTLINE.map(point => point.clone().applyMatrix4(camera.matrixWorldInverse)));
  const scale = Math.min((width - 2 * sides) / (bounds.max.x - bounds.min.x),
    (height - top - bottom) / (bounds.max.y - bounds.min.y));
  if (scale <= 0) return;
  const center = bounds.getCenter(new THREE.Vector3());
  center.y += (top - bottom) / (2 * scale);
  Object.assign(camera, {
    left: center.x - width / (2 * scale), right: center.x + width / (2 * scale),
    top: center.y + height / (2 * scale), bottom: center.y - height / (2 * scale),
  });
  camera.updateProjectionMatrix();
}

export function projectHouseLabels(camera, width, height, cleanerPosition, viewer = false) {
  const point = new THREE.Vector3();
  const project = (position) => {
    point.fromArray(position).project(camera);
    return { x: (point.x + 1) * width / 2, y: (1 - point.y) * height / 2 };
  };
  const bounds = (min, max) => {
    const corners = [min[0], max[0]].flatMap((x) =>
      [min[1], max[1]].flatMap((y) => [min[2], max[2]].map((z) => project([x, y, z]))));
    return {
      left: Math.min(...corners.map(({ x }) => x)), right: Math.max(...corners.map(({ x }) => x)),
      top: Math.min(...corners.map(({ y }) => y)), bottom: Math.max(...corners.map(({ y }) => y)),
    };
  };
  const anchors = Object.fromEntries(Object.entries(LABEL_ANCHORS).map(([id, position]) => [id, project(position)]));
  if (cleanerPosition) anchors.cleaner_01 = project([cleanerPosition.x, .50, cleanerPosition.z]);
  const { width: w, height: h, center: [x, y, z] } = TV_SCREEN;
  const [px, py, pz] = PENDANT;
  return {
    anchors,
    screen: bounds([x - w / 2, y - h / 2, z], [x + w / 2, y + h / 2, z]),
    pendant: bounds([px - .49, py - .24, pz - .49], [px + .49, py + .65, pz + .49]),
    floor: viewer ? bounds([-3.95, .08, -.95], [.4, .67, 2.8])
      : bounds([-4.96, .08, -3.54], [1.46, .08, 3.72]),
    ...(viewer ? { table: bounds([2.57, .08, .65], [5.75, 1.05, 3.04]) } : {}),
  };
}

export function layoutViewerLabels(markers, width, height, clearance) {
  const gap = 8;
  const clamp = THREE.MathUtils.clamp;
  const placed = [];
  const obstacles = Object.values(clearance).filter(Boolean);
  const ordered = [...markers].sort((a, b) => Number(b.required) - Number(a.required) || a.y - b.y);
  for (const box of ordered) {
    const { id, x, y, width: w, height: h } = box;
    if (w > width - 2 * gap || h > height - 54 - gap) continue;
    const side = id === "light_01" ? clearance.pendant : null;
    const table = id === "oven_01" ? clearance.table : null;
    const above = [x - w / 2, y - h - 12];
    const candidates = [
      ...(side ? [[side.left - w - gap, y - h / 2]] : []),
      above, [x - w - gap, y - h - gap], [x + gap, y - h - gap],
      [x - w - gap, y - h / 2], [x + gap, y - h / 2], [x - w / 2, y + gap],
      ...(table ? [[table.right + gap, y + gap], [table.right + gap, y + h / 2]] : []),
    ];
    const blockers = [...obstacles, ...placed];
    const alternatives = [];
    for (const other of blockers) {
      alternatives.push([above[0], other.top - h - gap], [other.left - w - gap, above[1]],
        [other.right + gap, above[1]], [above[0], other.bottom + gap]);
    }
    const distance = ([left, top]) => (left - above[0]) ** 2 + (top - above[1]) ** 2;
    candidates.push(...alternatives.sort((a, b) => distance(a) - distance(b)));
    for (const [candidateX, candidateY] of candidates) {
      const left = clamp(candidateX, gap, width - w - gap);
      const top = clamp(candidateY, 54, height - h - gap);
      const right = left + w, bottom = top + h;
      if (blockers.some(other => left < other.right + gap && right > other.left - gap &&
          top < other.bottom + gap && bottom > other.top - gap)) continue;
      placed.push({ ...box, left, top, right, bottom });
      break;
    }
  }
  return placed;
}

export function layoutHouseLabels(markers, viewWidth, viewHeight, { screen, pendant, floor } = {}) {
  const gap = 8;
  const minTop = 46;
  const bottom = viewHeight - 44;
  const clamp = THREE.MathUtils.clamp;
  const obstacles = [screen, pendant, floor].filter(Boolean);
  const priority = ({ focused, required }) => focused ? 2 : required ? 1 : 0;
  const boxes = markers.filter(({ width, height }) => width <= viewWidth - 2 * gap && height <= bottom - minTop)
    .sort((a, b) => priority(b) - priority(a) || a.y - b.y);
  const placed = [];
  for (const box of boxes) {
    const { id, x, y, width, height } = box;
    const toSide = id === "light_01" && pendant;
    const preferredLeft = clamp(toSide ? pendant.left - width - 12 : x - width / 2, gap, viewWidth - width - gap);
    const preferredTop = clamp(y - (toSide ? height / 2 : height + 12), minTop, bottom - height);
    const blockers = [...obstacles, ...placed];
    const columns = [preferredLeft];
    if (priority(box)) {
      columns.push(...blockers.flatMap((other) => [other.left - width - gap, other.right + gap]));
      columns.sort((a, b) => Math.abs(a - preferredLeft) - Math.abs(b - preferredLeft));
    }
    let best, distance = Infinity;
    for (const left of columns) {
      const horizontal = (left - preferredLeft) ** 2;
      if (horizontal >= distance) break;
      const right = left + width;
      if (left < gap || right > viewWidth - gap) continue;
      const column = blockers.filter((other) => left < other.right + gap && right > other.left - gap);
      const rows = [preferredTop];
      if (priority(box)) {
        rows.push(...column.flatMap((other) => [other.top - height - gap, other.bottom + gap]));
        rows.sort((a, b) => Math.abs(a - preferredTop) - Math.abs(b - preferredTop));
      }
      const top = rows.find((row) => row >= minTop && row + height <= bottom &&
        column.every((other) => row >= other.bottom + gap || row + height + gap <= other.top));
      if (top === undefined) continue;
      const score = horizontal + (top - preferredTop) ** 2;
      if (score < distance) {
        best = { ...box, left, right, top, bottom: top + height };
        distance = score;
      }
    }
    if (best) placed.push(best);
  }
  return placed;
}

export function replaceHouseMarkers(current, next) {
  const focused = current.contains(document.activeElement) ? document.activeElement.id : "";
  const openNotice = CSS.supports("selector(:popover-open)") &&
    current.querySelector(".notice-detail:popover-open")?.id;
  current.replaceWith(next);
  if (focused) document.getElementById(focused)?.focus({ preventScroll: true });
  if (openNotice) document.getElementById(openNotice)?.showPopover();
}

// The fixed I1 cutaway. View direction and entrance cues are separate from device values.
export function createHouse(stage, { decorateLabel, viewer = false } = {}) {
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const renderer = new THREE.WebGLRenderer({antialias:true, alpha:true});
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.16;
  stage.append(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera();
  const lamp = new THREE.PointLight(WARM_WHITE, 0, 4.0, 2);
  lamp.position.set(-1.42, 2.44, -.23);
  const kitchenLight = new THREE.PointLight("#fff7ec", 14, 4.3, 2);
  kitchenLight.position.set(4.18, 3.05, -.76);
  scene.add(lamp, kitchenLight);

  const roomLighting = {
    livingTint: { value: lamp.color },
    livingLevel: { value: 0 },
    tvFloorTint: { value: new THREE.Color() },
    tvWallTint: { value: new THREE.Color() },
    tvLevel: { value: 0 },
  };

  function addRoomLighting(shader) {
    Object.assign(shader.uniforms, roomLighting);
    shader.vertexShader = `varying vec3 housePosition;\n${shader.vertexShader}`.replace(
      "#include <worldpos_vertex>",
      "#include <worldpos_vertex>\nhousePosition = (modelMatrix * vec4(transformed, 1.0)).xyz;",
    );
    shader.fragmentShader = `
      varying vec3 housePosition;
      uniform vec3 livingTint, tvFloorTint, tvWallTint;
      uniform float livingLevel, tvLevel;
      ${shader.fragmentShader}
    `.replace("#include <opaque_fragment>", `
      // Bounce falls across the actual surfaces and fades at the room boundaries.
      if (housePosition.x > -5.05 && housePosition.x < 1.48) {
        vec3 lampOffset = (housePosition - vec3(-1.48, 0.55, -0.20)) / vec3(4.0, 3.0, 5.4);
        float roomEdge = smoothstep(-5.05, -4.24, housePosition.x)
                        * (1.0 - smoothstep(0.52, 1.48, housePosition.x));
        float bounce = livingLevel * roomEdge * (1.0 - smoothstep(0.10, 1.12, length(lampOffset)));
        vec3 litSurface = outgoingLight * mix(vec3(1.0), livingTint, 0.9);
        litSurface += (0.18 + 0.55 * diffuseColor.rgb) * livingTint;
        outgoingLight = mix(outgoingLight, litSurface, bounce);

        if (tvLevel > 0.0) {
          vec3 tvOffset = (housePosition - vec3(-0.70, 1.24, -3.45)) / vec3(1.92, 2.4, 2.36);
          float reflection = tvLevel * roomEdge * (1.0 - smoothstep(0.18, 1.0, length(tvOffset)));
          vec3 screenTint = mix(tvFloorTint, tvWallTint, smoothstep(0.10, 2.22, housePosition.y));
          outgoingLight += (0.13 + 0.32 * diffuseColor.rgb) * screenTint * reflection;
        }
      }
      #include <opaque_fragment>
    `);
  }

  const mainLight = new THREE.DirectionalLight("#fff0d8", 2.4);
  mainLight.position.set(-5,12,7); mainLight.castShadow = true;
  Object.assign(mainLight.shadow.camera,{left:-11,right:11,top:9,bottom:-9,near:.5,far:35});
  mainLight.shadow.mapSize.set(2048,2048);
  mainLight.shadow.normalBias = .03;
  scene.add(mainLight, new THREE.HemisphereLight("#fff5e7","#ac8877",1.65));
  const fill = new THREE.DirectionalLight("#eee6ff", .75);
  fill.position.set(5,5,-7); scene.add(fill);

  function material(color, props = {}) {
    const surface = new THREE.MeshStandardMaterial({ color, roughness: .78, ...props });
    surface.onBeforeCompile = addRoomLighting;
    return surface;
  }
  const oak=material("#b98f65"), wood=material("#936d51"), stone=material("#efe4ca"), wall=material("#e9dfca");
  const sage=material("#777d68"), cream=material("#e5c8a5"), dark=material("#403936"), glass=material("#292334",{roughness:.29});
  const brass=material("#ad7544",{metalness:.5,roughness:.31}), linen=material("#b18b72"), ivory=material("#eee0c5");
  const steel=material("#c4a99f",{metalness:.31}), tile=material("#c4b49e");
  const foliage=["#65744e","#88946a","#a3a67a"].map(color=>material(color));
  const roundGeometry = new Map();
  function roundedGeometry(w,h,d,r) {
    const key = [w,h,d,r].join(",");
    if (roundGeometry.has(key)) return roundGeometry.get(key);
    const bevel = Math.min(r,w*.22,h*.22,d*.22);
    const x=w/2-bevel,y=h/2-bevel;
    const shape = new THREE.Shape();
    shape.moveTo(-x,-y); shape.lineTo(x,-y); shape.lineTo(x,y); shape.lineTo(-x,y); shape.closePath();
    const geo = new THREE.ExtrudeGeometry(shape,{depth:d-2*bevel,bevelEnabled:true,bevelSize:bevel,bevelThickness:bevel,bevelSegments:3,steps:1});
    geo.translate(0,0,-d/2+bevel);
    roundGeometry.set(key,geo);
    return geo;
  }
  function mesh(geometry, surface, x,y,z,parent=scene) {
    const object = new THREE.Mesh(geometry,surface);
    object.position.set(x,y,z); object.castShadow=true;object.receiveShadow=true;parent.add(object);return object;
  }
  function box(w,h,d,s,x,y,z,r=.035,parent=scene) {
    return mesh(roundedGeometry(w,h,d,r),s,x,y,z,parent);
  }
  function disk(r,h,s,x,y,z,parent=scene,bottom=r) {
    return mesh(new THREE.CylinderGeometry(r,bottom,h,48),s,x,y,z,parent);
  }
  function sphere(w,h,d,s,x,y,z,parent=scene) {
    const object=mesh(new THREE.SphereGeometry(1,24,14),s,x,y,z,parent);
    object.scale.set(w,h,d);return object;
  }
  function tube(points,r,s,parent=scene) {
    const path=new THREE.CatmullRomCurve3(points.map(point=>new THREE.Vector3(...point)));
    return mesh(new THREE.TubeGeometry(path,24,r,8,false),s,0,0,0,parent);
  }
  function plane(w,h,s,x,y,z,parent=scene) {
    const object=mesh(new THREE.PlaneGeometry(w,h),s,x,y,z,parent);
    object.castShadow=false;return object;
  }
  function group(x,y,z) {
    const object=new THREE.Group();object.position.set(x,y,z);scene.add(object);return object;
  }
  function canvasTexture(width,height,draw) {
    const canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;
    const ctx=canvas.getContext("2d");const texture=new THREE.CanvasTexture(canvas);
    texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=renderer.capabilities.getMaxAnisotropy();
    return {texture, paint(painter=draw){painter(ctx,width,height);texture.needsUpdate=true}};
  }
  function textile(base, thread) {
    const surface=canvasTexture(512,256,(ctx,w,h)=>{
      ctx.fillStyle=base;ctx.fillRect(0,0,w,h);
      for(let i=0;i<3000;i++){
        ctx.globalAlpha=.13 + (i%6)*.045;ctx.fillStyle=thread;
        ctx.fillRect((i*239)%w,(i*137)%h,1+(i%6),1);
      }
      ctx.globalAlpha=1;
    });
    surface.paint();
    return material("#ffffff",{map:surface.texture,bumpMap:surface.texture,bumpScale:.025});
  }

  const backing = new THREE.Mesh(new THREE.PlaneGeometry(120,120),new THREE.ShadowMaterial({opacity:.16}));
  backing.rotation.x=-Math.PI/2;backing.position.y=-.48;backing.receiveShadow=true;scene.add(backing);
  box(13.6,.42,7.95,material("#d6b498"),0,-.22,0,.12);
  box(13.35,.12,7.73,stone,0,-.026,0,.08);
  const planks=["#c48e61","#c5956b","#c99768","#d0a276","#d2a576","#c99265"].map(color=>material(color));
  for(let row=0;row<19;row++){
    const z=-3.54+row*.393;
    let x=-4.96,n=0;
    while (x<1.46){
      const width=Math.min(n===0?[.74,1.29,1.82][row%3]:2.1,1.46-x);
      if(width>.035) box(width-.015,.04,.378,planks[(row*7+n*3)%planks.length],x+width/2,.055,z,.009);
      x+=width;n++;
    }
  }
  for(let row=0;row<10;row++) for(let col=0;col<7;col++){
    box(.724,.028,.735,(row+col)%4===0?stone:tile,1.852+col*.74,.052,-3.38+row*.75,.006);
  }
  for(let row=0;row<10;row++) for(let col=0;col<3;col++){
    box(.52,.025,.737,(row+col)%2===0?tile:stone,-6.35+col*.535,.052,-3.38+row*.75,.006);
  }

  box(13.38,2.70,.22,wall,0,1.37,-3.85,.05);
  box(13.35,.15,.076,ivory,0,.15,-3.705,.012);
  box(.22,2.7,2.3,wall,-6.61,1.37,-2.78,.035);
  box(1.43,2.36,.10,oak,-5.73,1.23,-3.685,.048);
  box(1.16,2.13,.06,wood,-5.73,1.23,-3.61,.045);
  box(.028,1.78,.023,oak,-6.11,1.23,-3.57,.006);
  const entrySignal=material("#694a3c",{emissive:"#f0bc82",emissiveIntensity:0});
  box(.10,.24,.06,entrySignal,-5.29,1.17,-3.53,.02);
  box(1.22,.035,.79,textile("#7e6654","#b5a089"),-5.73,.07,-2.19,.06);
  box(1.36,.46,.49,oak,-5.77,.38,1.93,.06);
  box(1.25,.12,.53,cream,-5.77,.66,1.93,.045);
  for(const x of [-6.26,-5.27]) box(.10,.22,.36,wood,x,.16,1.93,.02);
  const parcel=group(-5.68,.08,-1.65);
  box(.54,.42,.46,material("#bf8e5f"),0,.22,0,.035,parcel);
  box(.089,.427,.474,cream,0,.23,0,.006,parcel);
  box(.20,.012,.12,ivory,.12,.449,.055,.003,parcel);

  const styler=group(-6.14,.075,.58);
  box(.65,1.96,.57,material("#baa391"),0,.98,0,.062,styler);
  box(.58,1.85,.063,ivory,0,1.02,.307,.046,styler);
  box(.041,.43,.047,brass,.207,1.05,.35,.013,styler);
  box(.13,.085,.016,glass,0,1.63,.345,.017,styler);
  box(.49,.055,.45,dark,0,.042,0,.013,styler);

  const windowGlass=material("#d6e5de",{emissive:"#d7e5e3",emissiveIntensity:.35});
  box(2.03,1.49,.05,wood,-3.85,1.68,-3.697,.035);
  box(1.84,1.31,.06,windowGlass,-3.85,1.68,-3.657,.03);
  box(.05,1.33,.06,ivory,-3.85,1.68,-3.61,.02);
  box(1.87,.06,.06,ivory,-3.85,1.72,-3.61,.01);
  box(2.24,.10,.25,ivory,-3.85,.95,-3.60,.025);
  for(let pleat=0;pleat<12;pleat++){
    const x=-4.95+(pleat%6)*.077+(pleat>5?1.81:0);
    box(.108,1.78,.11,pleat%2?ivory:cream,x,1.58,-3.51+(pleat%2)*.027,.037);
  }
  tube([[-5.02,2.52,-3.46],[-3.81,2.52,-3.46],[-2.60,2.52,-3.46]],.025,brass);

  box(3.83,.052,2.64,textile("#d5b59d","#805f4c"),-1.77,.10,.46,.11);
  const carpetLines=material("#ddc5ad");
  for (const z of [-.69,1.61]) box(3.52,.008,.023,carpetLines,-1.77,.13,z,.002);
  for(let i=0;i<40;i++) for(const z of [-.89,1.80]) box(.024,.012,.107,carpetLines,-3.55+i*.091,.119,z,.003);

  const fabric=textile("#dfc5a8","#8c7355");
  box(3.18,.36,.98,fabric,-1.86,.35,2.38,.14);
  box(3.17,.64,.25,fabric,-1.86,.65,2.78,.09);
  for(const x of [-3.30,-.42]){
    box(.28,.49,1.10,fabric,x,.56,2.38,.09);
    for(const z of [2.02,2.77]) box(.095,.22,.10,wood,x,.18,z,.022);
  }
  for(const x of [-2.56,-1.16]){
    box(1.32,.16,.69,fabric,x,.543,2.25,.09);
    const cushion=box(1.30,.48,.19,fabric,x,.798,2.57,.08);cushion.rotation.x=-.11;
  }
  const pillow=box(.44,.43,.22,linen,-2.98,.83,2.47,.09);pillow.rotation.z=-.19;
  const pillow2=box(.43,.40,.23,sage,-.79,.81,2.49,.09);pillow2.rotation.z=.23;
  const throwFold=box(.52,.052,.53,textile("#e9d2a8","#aa8669"),-.62,.835,2.50,.019);
  throwFold.rotation.z=-.08;
  const coffee=disk(.76,.09,oak,-1.69,.57,.54);coffee.scale.set(1.25,1,.71);
  for(const [x,z] of [[-2.06,.38],[-1.26,.37],[-1.69,.78]]) disk(.055,.45,wood,x,.31,z,scene,.068);
  box(.37,.047,.26,cream,-1.93,.64,.54,.01).rotation.y=.16;
  box(.31,.033,.22,sage,-1.94,.68,.54,.01).rotation.y=.10;
  disk(.115,.078,ivory,-1.36,.66,.45,scene,.075);
  disk(.082,.005,wood,-1.36,.702,.45);
  function plant(x,y,z,scale){
    const plantGroup=group(x,y,z);plantGroup.scale.setScalar(scale);
    disk(.24,.38,linen,0,.23,0,plantGroup,.18);disk(.215,.016,wood,0,.423,0,plantGroup);
    for(let i=0;i<8;i++){
      const angle=i*2.399, dx=Math.cos(angle)*(.22+i*.016), dz=Math.sin(angle)*(.22+i*.016), top=.68+(i%4)*.105;
      tube([[0,.43,0],[dx*.35,top-.11,dz*.35],[dx,top,dz]],.014,foliage[0],plantGroup);
      const leaf=sphere(.092,.036,.23,foliage[i%3],dx,top,dz,plantGroup);leaf.rotation.set(.35-i*.08,angle,.10);
    }
  }
  plant(1.00,.075,-1.96,1.35);plant(-4.45,.075,2.90,.79);

  const purifier=group(-3.95,.075,-2.16);
  disk(.228,.055,dark,0,.028,0,purifier);
  disk(.236,.66,ivory,0,.365,0,purifier,.218);
  for(let i=0;i<5;i++) disk(.238-i*.001,.012,steel,0,.137+i*.046,0,purifier);
  disk(.191,.025,dark,0,.704,0,purifier);
  for(let i=-2;i<=2;i++) box(.24,.011,.015,steel,0,.721,i*.052,.004,purifier);

  const speaker=group(-2.46,.08,-3.19);
  speaker.visible = false;
  box(.38,.72,.35,dark,0,.36,0,.06,speaker);
  box(.32,.62,.055,textile("#514a47","#a99989"),0,.36,.18,.035,speaker);

  box(2.27,.48,.60,oak,-.72,.35,-3.15,.055);
  for(let i=0;i<3;i++){
    const x=-1.44+i*.72;
    box(.68,.35,.026,wood,x,.36,-2.84,.025);
    for(let slat=0;slat<8;slat++) box(.024,.30,.021,oak,x-.26+slat*.072,.36,-2.818,.006);
  }
  for(const x of [-1.52,.13]) box(.16,.11,.40,wood,x,.12,-3.14,.03);
  const tvTexture=canvasTexture(1024,576);
  const tvMaterial=new THREE.MeshBasicMaterial({map:tvTexture.texture,color:"#ffffff",toneMapped:false});
  const display=group(0,0,0);
  box(2.25,1.28,.10,dark,-.70,1.52,-3.48,.057,display);
  const tvScreen = plane(TV_SCREEN.width, TV_SCREEN.height, tvMaterial, ...TV_SCREEN.center, display);
  const musicAnchor = new THREE.Vector3(.18, 1.10, -3.419);
  const musicPosition = new THREE.Vector3();
  const musicCue = document.createElement("span");
  musicCue.className = "tv-music";
  musicCue.setAttribute("aria-hidden", "true");
  musicCue.hidden = true;
  musicCue.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
  stage.append(musicCue);

  const pendant = group(...PENDANT);
  mesh(new THREE.LatheGeometry([
    new THREE.Vector2(.10,.16),new THREE.Vector2(.16,.16),new THREE.Vector2(.19,.09),
    new THREE.Vector2(.49,-.17),new THREE.Vector2(.49,-.22),new THREE.Vector2(.46,-.23),
    new THREE.Vector2(.16,.08),new THREE.Vector2(.10,.10)
  ],48),material("#f3d6af",{side:THREE.DoubleSide}),0,0,0,pendant);
  const lampSource=material(LAMP_SHADE,{emissive:WARM_WHITE,emissiveIntensity:0});
  const lampFace = disk(.43,.016,lampSource,0,-.22,0,pendant);
  disk(.053,.47,brass,0,.37,0,pendant);
  disk(.15,.061,brass,0,.61,0,pendant);
  const livingLight = createLivingLight(lamp, lampSource, roomLighting.livingLevel);

  const cleanerModel=group(0,0,0);
  box(.53,.19,.30,dark,.82,.16,-2.82,.055,cleanerModel);
  const cleaner=group(.82,.064,-2.59);
  cleanerModel.add(cleaner);
  disk(.275,.098,dark,0,.062,0,cleaner);disk(.264,.064,ivory,0,.125,0,cleaner);
  disk(.082,.052,steel,-.07,.171,-.053,cleaner);disk(.058,.014,dark,-.07,.200,-.053,cleaner);
  const vacuumLed=material("#778875",{emissive:"#85bfb6",emissiveIntensity:.3});
  disk(.020,.007,vacuumLed,.088,.159,.03,cleaner);
  const dock = cleaner.position.clone();
  const trailMaterial = new THREE.MeshBasicMaterial({color:"#66715f",transparent:true,opacity:.62});
  const cleaningTrail = [];
  const route = [[.61,-2.27],[.42,-1.73],[.53,-.70],[.94,.38],[.71,1.21],[.44,1.88],[.61,2.80]];
  const routeCurve=new THREE.CatmullRomCurve3(route.map(([x,z])=>new THREE.Vector3(x,.078,z)));
  for(let i=0;i<=22;i++){
    const point=routeCurve.getPoint(i/22);
    const dot=disk(.020,.009,trailMaterial,point.x,point.y,point.z,cleanerModel);dot.castShadow=false;cleaningTrail.push(dot);
  }

  const cabinet=material("#aba68b");
  box(4.31,.87,.98,cabinet,3.72,.52,-3.10,.047);
  box(4.43,.105,1.09,ivory,3.72,1.015,-3.08,.047);
  box(4.45,.34,.036,stone,3.73,1.235,-3.712,.010);
  for(let i=0;i<14;i++) box(.012,.29,.016,tile,1.66+i*.314,1.245,-3.685,.003);
  for(const x of [1.96,2.52,3.09,4.51,5.04,5.56]){
    box(.51,.72,.048,cabinet,x,.54,-2.585,.033);
    box(.496,.676,.019,sage,x,.54,-2.556,.023);
    box(.397,.562,.019,cabinet,x,.54,-2.543,.018);
    box(.17,.022,.049,brass,x,.795,-2.505,.008);
  }

  const cooktop=group(0,0,0);
  box(1.18,.063,.65,glass,2.24,1.088,-3.03,.034,cooktop);
  function ring(radius,stroke,s,x,y,z,parent) {
    const object=mesh(new THREE.TorusGeometry(radius,stroke,8,42),s,x,y,z,parent);
    object.rotation.x=-Math.PI/2;return object;
  }
  const burner=material("#60576a");
  ring(.157,.009,burner,2.00,1.124,-3.00,cooktop);
  ring(.107,.008,burner,2.43,1.124,-3.13,cooktop);
  ring(.079,.008,burner,2.50,1.124,-2.88,cooktop);
  const lockMaterial=material("#9c5c54",{emissive:"#ef7852",emissiveIntensity:0});
  const lockIcon=box(.12,.012,.096,lockMaterial,2.25,1.128,-2.755,.010,cooktop);
  const lockShackle=ring(.039,.011,lockMaterial,2.25,1.13,-2.807,cooktop);

  const oven=group(0,0,0);
  box(1.05,.73,.14,dark,3.73,.59,-2.569,.052,oven);
  box(.93,.47,.053,glass,3.73,.49,-2.477,.036,oven);
  box(.82,.35,.015,dark,3.73,.49,-2.447,.048,oven);
  const ovenInterior = canvasTexture(128, 64, (ctx, w, h) => {
    const heat = ctx.createRadialGradient(w * .62, h * .21, 2, w * .54, h * .42, w * .52);
    heat.addColorStop(0, "#ffe0a7");
    heat.addColorStop(.43, "#b55726");
    heat.addColorStop(1, "#210e0a");
    ctx.fillStyle = heat;
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#62321f";
    ctx.fillRect(13, 39, w - 26, 2);
    ctx.fillRect(11, 49, w - 22, 2);
  });
  ovenInterior.paint();
  const ovenWindow=material("#292332",{
    roughness:.29, emissive:"#fff2dc", emissiveMap:ovenInterior.texture, emissiveIntensity:0,
  });
  const ovenDoor = plane(.74,.28,ovenWindow,3.73,.49,-2.437,oven);
  box(.76,.039,.064,steel,3.73,.711,-2.42,.012,oven);
  const ovenTexture=canvasTexture(600,150);
  const ovenScreenMaterial=new THREE.MeshBasicMaterial({map:ovenTexture.texture,toneMapped:false});
  const ovenScreen = plane(.77,.17,ovenScreenMaterial,3.73,.846,-2.488,oven);

  const kettle=group(0,0,0);
  box(.21,.27,.12,ivory,5.14,1.27,-3.53,.027,kettle);
  const plugLed=material("#778875",{emissive:"#78d6ae",emissiveIntensity:0});
  disk(.025,.012,plugLed,5.14,1.29,-3.452,kettle).rotation.x=Math.PI/2;
  tube([[5.14,1.17,-3.45],[5.23,1.08,-3.40],[5.38,1.11,-3.28]],.022,dark,kettle);
  disk(.203,.059,dark,5.43,1.10,-3.16,kettle);
  disk(.154,.39,material("#d1a37c"),5.43,1.32,-3.16,kettle,.176);
  disk(.154,.035,brass,5.43,1.522,-3.16,kettle);disk(.046,.05,wood,5.43,1.558,-3.16,kettle);
  tube([[5.55,1.44,-3.16],[5.67,1.43,-3.16],[5.67,1.22,-3.16],[5.55,1.22,-3.16]],.033,dark,kettle);
  tube([[5.30,1.31,-3.13],[5.22,1.39,-3.12],[5.20,1.47,-3.11]],.041,brass,kettle);

  const fridge=group(0,0,0);
  box(.95,2.20,1.04,steel,6.12,1.17,-3.23,.08,fridge);
  box(.91,1.57,.075,ivory,6.12,1.48,-2.665,.046,fridge);
  box(.91,.55,.075,ivory,6.12,.382,-2.665,.046,fridge);
  box(.034,.44,.069,steel,5.79,1.39,-2.603,.014,fridge);
  box(.38,.034,.070,steel,6.09,.56,-2.603,.013,fridge);
  const fridgeTexture=canvasTexture(360,420);
  const fridgeScreen=new THREE.MeshBasicMaterial({map:fridgeTexture.texture,toneMapped:false});
  box(.37,.47,.034,dark,6.18,1.64,-2.616,.025,fridge);
  // The notice stays legible while the appliance rests.
  const noticeScreen = plane(.329,.426,fridgeScreen,6.18,1.64,-2.595,fridge);

  const tableTop=disk(.82,.094,oak,4.15,.86,1.50);tableTop.scale.x=1.23;
  disk(.18,.74,wood,4.15,.44,1.50,scene,.25);disk(.36,.08,wood,4.15,.13,1.50);
  disk(.22,.065,ivory,4.15,.938,1.53,scene,.14);
  for(const [x,z,rotation] of [[4.03,2.69,0],[2.87,1.27,Math.PI/2],[5.43,1.55,-Math.PI/2]]){
    const chair=group(x,.08,z);chair.rotation.y=rotation;
    box(.61,.09,.58,oak,0,.49,0,.047,chair);
    box(.61,.37,.095,sage,0,.86,.255,.037,chair);
    for(const a of [-.23,.23])for(const b of [-.21,.21])disk(.038,b > 0 ? .76 : .45,wood,a,b > 0 ? .38 : .23,b,chair,.031);
  }

  const projected = new THREE.Vector3();
  const cleanPosition = new THREE.Vector3();
  const goalCamera = new THREE.Vector3();
  const goalTarget = new THREE.Vector3();
  const currentCamera = new THREE.Vector3();
  const currentTarget = new THREE.Vector3();
  const models = {
    cleaner_01: cleanerModel, light_01: pendant, display_01: display, cooktop_01: cooktop,
    oven_01: oven, fridge_01: fridge, plug_kettle: kettle,
    purifier_01: purifier, styler_01: styler, speaker_01: speaker,
  };
  const normalMaterials = new Map();
  const restingMaterials = new Map();
  const observedSurfaces = new Set([lampFace, tvScreen, ovenDoor, ovenScreen, noticeScreen]);
  const readings = new Map();
  let labels = new Map();
  let presentation = new Map();
  let jobRunning = false, cleanSince = 0, tvScene;
  let entranceSignal;
  let zoom = 1, targetZoom = 1, hasDirection = false;
  let viewWidth = 0, viewHeight = 0, request = 0, readyAt = 0;

  parcel.visible = false;
  lockIcon.visible = lockShackle.visible = false;
  cleaningTrail.forEach((dot) => { dot.visible = false; });
  const castle = new Image();
  castle.onload = () => {
    if (tvScene === "kids_party") {
      paintTv();
      queue();
    }
  };
  castle.src = new URL("./castle.jpg", import.meta.url).href;

  function paintTv() {
    tvTexture.paint((ctx, w, h) => {
      const look = TV_LOOKS[tvScene];
      ctx.fillStyle = "#17151f";
      ctx.fillRect(0, 0, w, h);
      if (!look) return;
      if (tvScene === "kids_party" && castle.naturalWidth) {
        const scale = Math.max(w / castle.naturalWidth, h / castle.naturalHeight);
        const width = castle.naturalWidth * scale, height = castle.naturalHeight * scale;
        ctx.drawImage(castle, (w - width) / 2, (h - height) / 2, width, height);
        return;
      }

      const sky = ctx.createLinearGradient(0, 0, 0, h);
      sky.addColorStop(0, look.sky[0]);
      sky.addColorStop(1, look.sky[1]);
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, h);
      if (tvScene === "party") {
        for (const [x, y, radius, color] of [
          [.23, .34, 103, "rgba(255,183,128,.63)"],
          [.51, .65, 158, "rgba(253,142,188,.64)"],
          [.78, .32, 134, "rgba(255,210,150,.59)"],
        ]) {
          const bokeh = ctx.createRadialGradient(w * x, h * y, 6, w * x, h * y, radius);
          bokeh.addColorStop(0, color);
          bokeh.addColorStop(1, "transparent");
          ctx.fillStyle = bokeh;
          ctx.fillRect(w * x - radius, h * y - radius, 2 * radius, 2 * radius);
        }
      } else if (tvScene === "calm") {
        ctx.fillStyle = "#dce5c7";
        ctx.beginPath();
        ctx.arc(.73 * w, .31 * h, .084 * h, 0, 2 * Math.PI);
        ctx.fill();
        ctx.fillStyle = "#456d69";
        ctx.beginPath();
        ctx.moveTo(0, .68 * h);
        ctx.bezierCurveTo(.28 * w, .23 * h, .48 * w, 1.06 * h, w, .55 * h);
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.fill();
      } else if (tvScene === "cinema") {
        ctx.fillStyle = "#c3c5f2";
        ctx.beginPath();
        ctx.arc(.39 * w, .46 * h, .19 * h, 0, 2 * Math.PI);
        ctx.fill();
        ctx.fillStyle = "#191b37";
        ctx.beginPath();
        ctx.moveTo(0, .79 * h);
        ctx.lineTo(.24 * w, .48 * h);
        ctx.lineTo(.45 * w, .75 * h);
        ctx.lineTo(.66 * w, .53 * h);
        ctx.lineTo(w, .77 * h);
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.fill();
        ctx.fillStyle = "#141220";
        ctx.fillRect(0, 0, w, .12 * h);
        ctx.fillRect(0, .88 * h, w, .12 * h);
      }
    });
  }

  function paintOven({ preset, in_use }) {
    const baking = in_use === true;
    ovenWindow.emissiveIntensity = baking ? 1.55 : 0;
    ovenTexture.paint((ctx, w, h) => {
      ctx.fillStyle = "#201e29";
      ctx.fillRect(0, 0, w, h);
      if (!preset) return;

      const glow = ctx.createRadialGradient(55, h / 2, 3, 55, h / 2, 50);
      glow.addColorStop(0, baking ? "#ffbb73" : "#e8aa58");
      glow.addColorStop(.21, baking ? "#cf732f" : "#996036");
      glow.addColorStop(1, "transparent");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 20, 110, h - 40);
      ctx.fillStyle = "#ffe3b5";
      ctx.font = '600 75px "IBM Plex Sans KR", sans-serif';
      ctx.textAlign = "center";
      ctx.fillText(`${preset.temp_c}° · ${preset.minutes}분`, w / 2 + 28, 101, w - 132);
    });
  }

  function paintFridge(notice) {
    fridgeTexture.paint((ctx, w, h) => {
      ctx.fillStyle = notice ? "#edf0dc" : "#2b2c2b";
      ctx.fillRect(0, 0, w, h);
      if (!notice) return;
      ctx.fillStyle = "#385447";
      ctx.font = '600 34px "IBM Plex Sans KR", sans-serif';
      ctx.fillText("냉장고 안내", 22, 58);
      ctx.fillRect(22, 79, w - 44, 3);
      ctx.font = '500 25px "IBM Plex Sans KR", sans-serif';
      let line = "", y = 122;
      for (const char of notice) {
        if (ctx.measureText(line + char).width > w - 44) {
          ctx.fillText(line, 22, y);
          line = "";
          y += 37;
        }
        line += char;
      }
      ctx.fillText(line, 22, y);
    });
  }

  const painters = {
    light_01(values) {
      return livingLight.update(values, performance.now());
    },
    display_01({ play_mood }) {
      const scene = play_mood?.scene;
      tvScene = Object.hasOwn(TV_LOOKS, scene) ? scene : null;
      musicCue.hidden = !tvScene;
      roomLighting.tvLevel.value = tvScene ? .72 : 0;
      if (tvScene) {
        const [floorTint, wallTint] = TV_LOOKS[tvScene].spill;
        roomLighting.tvFloorTint.value.set(floorTint);
        roomLighting.tvWallTint.value.set(wallTint);
      }
      paintTv();
      return tvScene === "kids_party";
    },
    oven_01: paintOven,
    fridge_01({ show_notice }) {
      paintFridge(show_notice);
    },
    cooktop_01({ child_lock }) {
      lockIcon.visible = lockShackle.visible = child_lock === true;
      lockMaterial.emissiveIntensity = child_lock ? .82 : 0;
    },
    plug_kettle({ power }) {
      plugLed.color.set(power ? "#778875" : "#8a6c5b");
      plugLed.emissive.set(power ? "#78d6ae" : "#b9946e");
      plugLed.emissiveIntensity = power ? 1.4 : 0;
    },
    cleaner_01({ job_status, in_use }) {
      const running = job_status === "running" || in_use === true;
      if (running && !jobRunning) cleanSince = performance.now();
      jobRunning = running;
      vacuumLed.emissiveIntensity = running ? 1.7 : .3;
      if (!running) {
        cleaner.position.copy(dock);
        cleaningTrail.forEach((dot) => { dot.visible = false; });
      }
    },
  };
  paintTv();
  paintOven({});
  paintFridge(null);
  Promise.all([
    document.fonts.load('500 25px "IBM Plex Sans KR"', "냉장고 안내"),
    document.fonts.load('600 75px "IBM Plex Sans KR"', "170° · 20분"),
  ]).then(() => {
    paintOven(readings.get("oven_01")?.values ?? {});
    paintFridge(readings.get("fridge_01")?.values.show_notice);
    queue();
  }).catch(() => {});

  function restingMaterial(normal) {
    if (!restingMaterials.has(normal)) {
      const muted = normal.clone();
      muted.onBeforeCompile = (shader) => {
        normal.onBeforeCompile(shader);
        // Apply after lighting so textures and emissive surfaces also rest.
        shader.fragmentShader = shader.fragmentShader.replace("#include <opaque_fragment>", `
          float luma = dot(outgoingLight, vec3(0.2126, 0.7152, 0.0722));
          outgoingLight = mix(vec3(luma), outgoingLight, 0.12) * 0.46;
          #include <opaque_fragment>
        `);
      };
      restingMaterials.set(normal, muted);
    }
    return restingMaterials.get(normal);
  }

  function setPresentation(next) {
    let changed = false;
    for (const [id, model] of Object.entries(models)) {
      const current = next.get(id) ?? {};
      const previous = presentation.get(id);
      if (Boolean(current.resting) !== Boolean(previous?.resting)) {
        model.traverse((object) => {
          if (!object.isMesh || observedSurfaces.has(object)) return;
          if (!normalMaterials.has(object)) normalMaterials.set(object, object.material);
          const normal = normalMaterials.get(object);
          object.material = current.resting ? restingMaterial(normal) : normal;
        });
      }
      if (JSON.stringify(current) !== JSON.stringify(previous ?? {})) {
        decorateDeviceLabel(id, current);
        changed = true;
      }
    }
    presentation = next;
    if (changed) queue();
  }

  function decorateDeviceLabel(id, appearance = {}) {
    const label = labels.get(id);
    if (!label) return;
    label.classList.toggle("focused", appearance.focused === true);
    decorateLabel?.(label, appearance);
  }

  function update(valuesById) {
    let changed = false;
    for (const [id, model] of Object.entries(models)) {
      if (model.visible !== valuesById.has(id)) {
        model.visible = valuesById.has(id);
        changed = true;
      }
    }
    for (const [id, paint] of Object.entries(painters)) {
      const values = valuesById.get(id) ?? {};
      const key = JSON.stringify(values);
      const previous = readings.get(id);
      if (previous?.key === key) continue;
      changed = true;

      const theme = paint(values) === true;
      readings.set(id, { key, values, theme });
    }
    if (changed) {
      renderer.shadowMap.needsUpdate = true;
      queue();
    }
  }

  function project(id) {
    if (id === "cleaner_01" && jobRunning) projected.set(cleaner.position.x, .50, cleaner.position.z);
    else projected.fromArray(LABEL_ANCHORS[id]);
    projected.project(camera);
    return { x: (projected.x + 1) / 2, y: (1 - projected.y) / 2 };
  }

  function placeLabels() {
    // Measure in stage pixels, before the outer frame scales to the screen.
    const inline = viewWidth >= 720;
    const { anchors, screen, pendant: shade, floor, table } = projectHouseLabels(camera, viewWidth, viewHeight,
      jobRunning ? cleaner.position : null, viewer);
    const clearance = {
      screen: display.visible ? screen : null,
      pendant: pendant.visible ? shade : null,
      floor: roomLighting.livingLevel.value > 0 || roomLighting.tvLevel.value > 0 ? floor : null,
    };
    if (viewer) clearance.table = table;
    for (const [id, label] of labels) {
      if (Object.hasOwn(anchors, id)) label.classList.toggle("anchored", inline);
    }
    const markers = Array.from(labels).flatMap(([id, label]) => {
      if (!Object.hasOwn(anchors, id)) return [];
      const focused = presentation.get(id)?.focused;
      return [{ id, label, focused, required: focused || label.hasAttribute("data-required"),
        ...anchors[id], width: label.offsetWidth, height: label.offsetHeight }];
    });
    const layout = viewer ? layoutViewerLabels : layoutHouseLabels;
    const placements = inline ? layout(markers, viewWidth, viewHeight, clearance) : [];
    const placed = new Set(placements.map(({ label }) => label));
    for (const { id, label, required } of markers) {
      label.classList.toggle("anchored", placed.has(label));
      label.classList.toggle("unplaced", inline && !viewer && !required && !placed.has(label));
      label.classList.toggle("theme", !viewer && readings.get(id)?.theme === true);
    }
    for (const { label, x, y, left, right, top, bottom, height } of placements) {
      label.style.left = `${left}px`;
      label.style.top = `${top}px`;
      if (viewer) {
        const startX = THREE.MathUtils.clamp(x, left, right);
        const startY = THREE.MathUtils.clamp(y, top, bottom);
        label.style.setProperty("--leader-x", `${startX - left}px`);
        label.style.setProperty("--leader-top", `${startY - top}px`);
        label.style.setProperty("--leader-length", `${Math.hypot(x - startX, y - startY)}px`);
        label.style.setProperty("--leader-angle", `${Math.atan2(y - startY, x - startX)}rad`);
        continue;
      }
      const crosses = Object.values(clearance).some((area) => area && x >= area.left && x <= area.right &&
        Math.min(top, y) < area.bottom && Math.max(bottom, y) > area.top);
      const length = x < left || x > right || crosses ? 0 : Math.max(top - y, y - bottom, 0);
      label.style.setProperty("--leader-x", `${x - left}px`);
      label.style.setProperty("--leader-top", `${Math.min(y - top, height)}px`);
      label.style.setProperty("--leader-height", `${length}px`);
    }
  }

  function setMarkers(root) {
    const devices = [...root.querySelectorAll("[data-device][data-values]")];
    labels = new Map(devices.map((node) => [node.dataset.device, node]));
    update(new Map(devices.map((node) => [node.dataset.device, JSON.parse(node.dataset.values)])));
    for (const id of labels.keys()) decorateDeviceLabel(id, presentation.get(id));
    const entrance = root.querySelector("#entrance-observations");
    if (entrance) labels.set("entrance", entrance);
    queue();
  }

  function syncViewport() {
    const width = stage.clientWidth, height = stage.clientHeight;
    if (!width || !height) return false;
    const scale = stage.getBoundingClientRect().width / width;
    const ratio = Math.min(devicePixelRatio * scale, 1.5);
    if (width === viewWidth && height === viewHeight && ratio === renderer.getPixelRatio()) return false;
    viewWidth = width;
    viewHeight = height;
    renderer.setPixelRatio(ratio);
    renderer.setSize(width, height, false);
    return true;
  }

  function resize() {
    syncViewport();
    queue();
  }

  function focus(setting = OVERVIEW, { instant = false } = {}) {
    goalCamera.fromArray(setting.eye);
    goalTarget.fromArray(setting.aim);
    targetZoom = setting.zoom;
    if (!hasDirection || instant || motion.matches) {
      currentCamera.copy(goalCamera);
      currentTarget.copy(goalTarget);
      zoom = targetZoom;
      orient();
    }
    hasDirection = true;
    queue();
  }

  function setEntrance({ packagePresent, signal }) {
    if (packagePresent === parcel.visible && signal === entranceSignal) return;
    entranceSignal = signal;
    parcel.visible = packagePresent;
    entrySignal.emissive.set(signal === "bell" ? "#f5d991" : "#f0bc82");
    entrySignal.emissiveIntensity = signal ? .9 : 0;
    renderer.shadowMap.needsUpdate = true;
    queue();
  }

  function queue() {
    readyAt = performance.now() + 1350;
    if (!request) request = requestAnimationFrame(frame);
  }

  function orient() {
    orientHouseCamera(camera, currentCamera, currentTarget, zoom, viewHeight ? viewWidth / viewHeight : 1);
    if (viewer && viewWidth && viewHeight) fitViewerCamera(camera, viewWidth, viewHeight);
  }

  function frame(now) {
    request = 0;
    if (!hasDirection || !stage.clientWidth) return;
    syncViewport();
    const amount = motion.matches || now > readyAt ? 1 : .093;
    currentCamera.lerp(goalCamera, amount);
    currentTarget.lerp(goalTarget, amount);
    zoom = THREE.MathUtils.lerp(zoom, targetZoom, amount);
    orient();
    livingLight.render(now, motion.matches);
    if (!musicCue.hidden) {
      musicPosition.copy(musicAnchor).project(camera);
      musicCue.style.left = `${(musicPosition.x + 1) * 50}%`;
      musicCue.style.top = `${(1 - musicPosition.y) * 50}%`;
    }
    if (jobRunning) {
      const progress = motion.matches ? .30 : ((now - cleanSince) % 6800) / 3400;
      const distance = 1 - Math.abs(1 - progress);
      routeCurve.getPoint(distance, cleanPosition);
      cleaner.position.set(cleanPosition.x, .064, cleanPosition.z);
      cleaningTrail.forEach((dot, index) => { dot.visible = index / 22 <= distance; });
      renderer.shadowMap.needsUpdate = true;
    }
    for (const [normal, muted] of restingMaterials) {
      muted.color.copy(normal.color);
      if (normal.emissive) {
        muted.emissive.copy(normal.emissive);
        muted.emissiveIntensity = normal.emissiveIntensity;
      }
    }
    renderer.render(scene, camera);
    placeLabels();
    if (!motion.matches && (now < readyAt || jobRunning)) request = requestAnimationFrame(frame);
  }

  new ResizeObserver(resize).observe(stage);
  return { resize, setPresentation, setMarkers, focus, setEntrance, anchor: project };
}
