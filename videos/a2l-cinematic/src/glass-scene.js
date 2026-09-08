import * as THREE from 'three';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';

window.__initA2L3D=()=>{
const renderer=new THREE.WebGLRenderer({canvas:document.getElementById('three-layer'),alpha:true,antialias:true,preserveDrawingBuffer:true});
renderer.setPixelRatio(1);renderer.setSize(1920,1080,false);renderer.setClearColor(0xf8faff,0);
renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.92;
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(34,1920/1080,.1,60);camera.position.set(0,0,14);camera.lookAt(0,0,0);
const env=new RoomEnvironment();const pmrem=new THREE.PMREMGenerator(renderer);scene.environment=pmrem.fromScene(env,.03).texture;env.dispose();pmrem.dispose();
scene.add(new THREE.HemisphereLight(0xffffff,0xc5cde2,1.4));
const key=new THREE.DirectionalLight(0xffffff,2.5);key.position.set(-4,9,5);scene.add(key);
const rim=new THREE.DirectionalLight(0xa2baff,2);rim.position.set(7,3,-4);scene.add(rim);
const warm=new THREE.DirectionalLight(0xffded4,1.2);warm.position.set(-6,-1,3);scene.add(warm);
const shadowCanvas=document.createElement('canvas');shadowCanvas.width=128;shadowCanvas.height=128;
const shadowContext=shadowCanvas.getContext('2d');const shadowGradient=shadowContext.createRadialGradient(64,64,0,64,64,64);shadowGradient.addColorStop(0,'rgba(83,97,141,.20)');shadowGradient.addColorStop(.4,'rgba(83,97,141,.10)');shadowGradient.addColorStop(1,'rgba(83,97,141,0)');shadowContext.fillStyle=shadowGradient;shadowContext.fillRect(0,0,128,128);
const floor=new THREE.Mesh(new THREE.PlaneGeometry(6,3),new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(shadowCanvas),transparent:true,depthWrite:false}));floor.rotation.x=-Math.PI/2;floor.position.set(3.1,-2.15,0);scene.add(floor);
const vault=new THREE.Group();scene.add(vault);
const colors=[0x7198e9,0xa18bdb,0xe5a188,0x81a5e8,0xa4b4e8];
const layers=[];
const glassGeometry=new RoundedBoxGeometry(3.2,.14,2.65,5,.065);
const paperGeometry=new RoundedBoxGeometry(2.93,.035,2.38,3,.015);
const glassMaterial=color=>new THREE.MeshPhysicalMaterial({color,metalness:.12,roughness:.16,transmission:.40,thickness:.48,ior:1.48,clearcoat:1,clearcoatRoughness:.09,envMapIntensity:1,transparent:true,opacity:1,attenuationColor:new THREE.Color(color),attenuationDistance:.9});
for(let i=0;i<5;i++){
 const layer=new THREE.Group();
 const glass=new THREE.Mesh(glassGeometry,glassMaterial(colors[i]));glass.castShadow=true;glass.receiveShadow=true;layer.add(glass);
 const paper=new THREE.Mesh(paperGeometry,new THREE.MeshPhysicalMaterial({color:0xeaf0fb,roughness:.35,metalness:.08,clearcoat:.7}));paper.position.y=.10;layer.add(paper);
 const tab=new THREE.Mesh(new RoundedBoxGeometry(.70,.09,.32,4,.04),glassMaterial(colors[i]));tab.position.set(-.95,.07,-1.35);layer.add(tab);
 const lineMaterial=new THREE.MeshStandardMaterial({color:i%2?0x9aaed8:0x95a0bd,metalness:.05,roughness:.6});
 for(let j=0;j<4;j++){const line=new THREE.Mesh(new THREE.BoxGeometry(1.9-j*.23,.008,.021),lineMaterial);line.position.set(-.22,.123,-.65+j*.27);layer.add(line);}
 const label=new THREE.Mesh(new RoundedBoxGeometry(.48,.015,.19,3,.02),new THREE.MeshStandardMaterial({color:colors[i],roughness:.35,metalness:.1}));label.position.set(.91,.123,.72);layer.add(label);
 vault.add(layer);layers.push(layer);
}
const clamp=THREE.MathUtils.clamp,mix=THREE.MathUtils.lerp;
const ease=(a,b,t)=>{const p=clamp((t-a)/(b-a),0,1);return p*p*(3-2*p);};
function renderAt(time){
 const t=clamp(Number(time)||0,0,18);
 vault.visible=t<4.65||(t>=15&&t<=18);floor.visible=vault.visible&&t<4.65;
 let scale=1.23,x=3.1,y=-.25,rx=.38,ry=-.65,rz=-.10,spread=.35;
 if(t<1.8){const p=ease(0,1.65,t);scale=mix(1.50,1.17,p);x=mix(3.5,3.1,p);ry=mix(-1.05,-.60,p);rx=.49;spread=mix(.55,.32,p);rz=-.10;}
 else if(t<4.8){const p=ease(1.8,2.3,t);scale=mix(1.17,.98,p)*(1-ease(4.35,4.65,t));x=mix(3.1,3.4,p);y=mix(-.25,-.33,p);rx=mix(.49,.45,p);ry=-.6+(t-1.8)*.11;rz=mix(-.10,-.03,p);spread=mix(.32,.34,p);}
 else if(t<15){const p=ease(12.5,13.1,t);scale=mix(.72,1.12,p);x=3.0;y=-.15;ry=-.8+(t-12.5)*.23;rx=.53;rz=-.03;spread=mix(.62,.33,p);}
 else{const p=ease(15,15.5,t);scale=mix(.08,.40,p);x=0;y=mix(2.08,2.25,p);ry=mix(-1.4,-.7,p);rx=.5;rz=0;spread=mix(.48,.29,p);}
 vault.position.set(x,y,0);vault.scale.setScalar(scale);vault.rotation.set(rx,ry,rz);
 layers.forEach((layer,i)=>{const k=i-2;const opening=t<1.8?1-ease(0,1.6,t):0;layer.position.set(k*.12*opening,k*spread,k*.10*opening);layer.rotation.set(0,k*.025*opening,0);});
 floor.position.y=t>=15?-3.1:-2.15;
 renderer.render(scene,camera);window.__a2l3dTime=t;
 // Publish a conservative screen-space envelope for the layout regression gate.
 // DOM collision tools cannot see geometry inside a canvas.
 const bounds=new THREE.Box3().setFromObject(vault);
 const corners=[];
 for(const bx of [bounds.min.x,bounds.max.x])for(const by of [bounds.min.y,bounds.max.y])for(const bz of [bounds.min.z,bounds.max.z]){
  const p=new THREE.Vector3(bx,by,bz).project(camera);
  corners.push({x:(p.x+1)*960,y:(1-p.y)*540});
 }
 window.__a2l3dBounds=vault.visible?{left:Math.min(...corners.map(p=>p.x)),right:Math.max(...corners.map(p=>p.x)),top:Math.min(...corners.map(p=>p.y)),bottom:Math.max(...corners.map(p=>p.y))}:null;
}
window.__renderA2L3D=renderAt;window.addEventListener('hf-seek',e=>renderAt(e.detail.time));renderAt(0);
};
