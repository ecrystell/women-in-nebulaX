import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { ExtrudeGeometry, Group, MathUtils, Shape } from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

const TRACK_ANGLE = 0.26;
const sideWindows = [-3.85, -3.2, -1.3, -0.68, 0.68, 1.3, 3.2, 3.85];
const doorPositions = [-2.25, 0, 2.25];

function trackOffsetForZ(z: number) {
  // The approach begins farther left, giving the train a longer diagonal pass.
  return -2.3 + MathUtils.clamp((z + 36) / 39, 0, 1) * 6.7;
}

function C151CabFront() {
  const shell = useMemo(() => {
    const profile = new Shape();
    profile.moveTo(-1.42, -1.04);
    profile.lineTo(1.42, -1.04);
    profile.lineTo(1.42, 0.42);
    profile.quadraticCurveTo(1.42, 1.12, 0.72, 1.34);
    profile.quadraticCurveTo(0, 1.54, -0.72, 1.34);
    profile.quadraticCurveTo(-1.42, 1.12, -1.42, 0.42);
    profile.lineTo(-1.42, -1.04);
    return new ExtrudeGeometry(profile, {
      depth: 1.08,
      bevelEnabled: true,
      bevelSegments: 4,
      bevelSize: 0.07,
      bevelThickness: 0.06,
      curveSegments: 20,
    });
  }, []);
  const windscreen = useMemo(() => new RoundedBoxGeometry(2.48, 1.42, 0.1, 8, 0.22), []);
  const destinationDisplay = useMemo(() => new RoundedBoxGeometry(0.9, 0.22, 0.05, 4, 0.04), []);

  return (
    <group>
      <mesh geometry={shell} position={[0, -0.06, 4.65]} castShadow>
        <meshStandardMaterial color="#e5eaed" metalness={0.72} roughness={0.22} />
      </mesh>
      <mesh geometry={windscreen} position={[0, 0.25, 5.82]}>
        <meshStandardMaterial color="#0a111b" metalness={0.48} roughness={0.09} />
      </mesh>
      <mesh geometry={destinationDisplay} position={[0, 0.82, 5.9]}>
        <meshStandardMaterial color="#d7dee2" emissive="#334155" emissiveIntensity={0.2} />
      </mesh>
      {[-0.56, 0.56].map((x) => (
        <mesh key={x} position={[x, -0.02, 5.9]} rotation={[0, 0, x < 0 ? -0.58 : 0.58]}>
          <boxGeometry args={[0.045, 0.66, 0.035]} />
          <meshStandardMaterial color="#334155" metalness={0.6} roughness={0.28} />
        </mesh>
      ))}
      <mesh position={[0, -0.39, 5.88]}>
        <boxGeometry args={[2.86, 0.29, 0.14]} />
        <meshStandardMaterial color="#d93f42" metalness={0.44} roughness={0.22} />
      </mesh>
      {[-0.84, 0.84].map((x) => (
        <group key={x} position={[x, -0.6, 5.91]}>
          <mesh>
            <boxGeometry args={[0.54, 0.3, 0.14]} />
            <meshStandardMaterial color="#3c4652" metalness={0.72} roughness={0.24} />
          </mesh>
          <mesh position={[0, 0, 0.075]}>
            <circleGeometry args={[0.105, 20]} />
            <meshStandardMaterial color="#fff7d6" emissive="#fff7d6" emissiveIntensity={2.8} />
          </mesh>
          <pointLight color="#fff7d6" intensity={22} distance={18} position={[0, 0, 0.32]} />
        </group>
      ))}
      <mesh position={[0, -0.93, 5.57]}>
        <boxGeometry args={[2.76, 0.25, 0.42]} />
        <meshStandardMaterial color="#1e293b" metalness={0.72} roughness={0.42} />
      </mesh>
      <mesh position={[0, -1.03, 5.88]}>
        <boxGeometry args={[0.48, 0.2, 0.46]} />
        <meshStandardMaterial color="#111827" metalness={0.74} roughness={0.4} />
      </mesh>
    </group>
  );
}

function MRTCar() {
  const body = useMemo(() => new RoundedBoxGeometry(2.72, 1.7, 9.24, 8, 0.16), []);
  const roof = useMemo(() => new RoundedBoxGeometry(2.38, 0.32, 9.18, 8, 0.14), []);

  return (
    <group>
      <mesh geometry={body} castShadow receiveShadow>
        <meshStandardMaterial color="#d7dde3" metalness={0.74} roughness={0.3} />
      </mesh>
      <mesh position={[0, -0.73, 0]}>
        <boxGeometry args={[2.78, 0.28, 9.38]} />
        <meshStandardMaterial color="#334155" metalness={0.62} roughness={0.4} />
      </mesh>
      <mesh geometry={roof} position={[0, 0.9, -0.14]}>
        <meshStandardMaterial color="#eef2f3" metalness={0.68} roughness={0.24} />
      </mesh>
      <mesh position={[0, 0.92, -0.65]}>
        <boxGeometry args={[2.28, 0.18, 7.6]} />
        <meshStandardMaterial color="#b8c1cc" metalness={0.7} roughness={0.35} />
      </mesh>
      {[-2.9, 0, 2.9].map((z) => (
        <mesh key={z} position={[0, 1.04, z]}>
          <boxGeometry args={[1.62, 0.1, 1.2]} />
          <meshStandardMaterial color="#64748b" metalness={0.62} roughness={0.48} />
        </mesh>
      ))}

      {[-1.39, 1.39].map((x) => (
        <group key={x} position={[x, 0.14, 0]}>
          <mesh>
          <boxGeometry args={[0.06, 0.77, 8.72]} />
            <meshStandardMaterial color="#172033" metalness={0.45} roughness={0.25} />
          </mesh>
          <mesh position={[x < 0 ? -0.035 : 0.035, -0.3, 0]}>
            <boxGeometry args={[0.07, 0.22, 9.42]} />
            <meshStandardMaterial color="#e74949" metalness={0.45} roughness={0.32} />
          </mesh>
          {sideWindows.map((z) => (
            <mesh key={z} position={[x < 0 ? -0.04 : 0.04, 0.1, z]}>
              <boxGeometry args={[0.08, 0.56, 0.78]} />
                <meshStandardMaterial color="#263445" emissive="#0f172a" emissiveIntensity={0.28} metalness={0.35} roughness={0.1} />
            </mesh>
          ))}
        </group>
      ))}

      {doorPositions.map((z) => (
        <group key={z}>
          {[-1.43, 1.43].map((x) => (
            <group key={x} position={[x, -0.04, z]}>
              <mesh>
                <boxGeometry args={[0.09, 1.05, 0.8]} />
                <meshStandardMaterial color="#0f172a" metalness={0.45} roughness={0.28} />
              </mesh>
              {[-0.195, 0.195].map((doorOffset) => (
                <mesh key={doorOffset} position={[x < 0 ? -0.05 : 0.05, 0, doorOffset]}>
                  <boxGeometry args={[0.11, 0.93, 0.36]} />
                  <meshStandardMaterial color="#d3dbe3" metalness={0.64} roughness={0.25} />
                </mesh>
              ))}
              <mesh position={[x < 0 ? -0.06 : 0.06, -0.29, 0]}>
                <boxGeometry args={[0.12, 0.2, 0.8]} />
                <meshStandardMaterial color="#d93f42" metalness={0.42} roughness={0.26} />
              </mesh>
            </group>
          ))}
        </group>
      ))}

      <C151CabFront />

      {[-3.25, 3.15].map((z) => (
        <group key={z} position={[0, -0.92, z]}>
          <mesh position={[0, 0, 0]}>
            <boxGeometry args={[2.25, 0.2, 1.12]} />
            <meshStandardMaterial color="#1e293b" metalness={0.7} roughness={0.42} />
          </mesh>
          {[-0.84, 0.84].map((x) => (
            <mesh key={x} position={[x, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
              <cylinderGeometry args={[0.42, 0.42, 0.18, 16]} />
              <meshStandardMaterial color="#111827" metalness={0.62} roughness={0.44} />
            </mesh>
          ))}
        </group>
      ))}
    </group>
  );
}

function PassengerCar({ position }: { position: [number, number, number] }) {
  const body = useMemo(() => new RoundedBoxGeometry(2.72, 1.7, 9.6, 8, 0.16), []);
  const roof = useMemo(() => new RoundedBoxGeometry(2.38, 0.32, 9.18, 8, 0.14), []);

  return (
    <group position={position}>
      <mesh geometry={body} castShadow receiveShadow>
        <meshStandardMaterial color="#d7dde3" metalness={0.74} roughness={0.3} />
      </mesh>
      <mesh position={[0, -0.73, 0]}>
        <boxGeometry args={[2.78, 0.28, 9.72]} />
        <meshStandardMaterial color="#334155" metalness={0.62} roughness={0.4} />
      </mesh>
      <mesh position={[0, 0.92, 0]}>
        <boxGeometry args={[2.28, 0.18, 8.25]} />
        <meshStandardMaterial color="#b8c1cc" metalness={0.7} roughness={0.35} />
      </mesh>
      <mesh geometry={roof} position={[0, 0.9, 0]}>
        <meshStandardMaterial color="#eef2f3" metalness={0.68} roughness={0.24} />
      </mesh>

      {[-1.39, 1.39].map((x) => (
        <group key={x} position={[x, 0.14, 0]}>
          <mesh>
            <boxGeometry args={[0.06, 0.77, 9.25]} />
            <meshStandardMaterial color="#172033" metalness={0.45} roughness={0.25} />
          </mesh>
          <mesh position={[x < 0 ? -0.035 : 0.035, -0.3, 0]}>
            <boxGeometry args={[0.07, 0.22, 9.72]} />
            <meshStandardMaterial color="#e74949" metalness={0.45} roughness={0.32} />
          </mesh>
          {sideWindows.map((z) => (
            <mesh key={z} position={[x < 0 ? -0.04 : 0.04, 0.1, z]}>
              <boxGeometry args={[0.08, 0.56, 0.78]} />
              <meshStandardMaterial color="#263445" emissive="#0f172a" emissiveIntensity={0.28} metalness={0.35} roughness={0.1} />
            </mesh>
          ))}
        </group>
      ))}

      {doorPositions.map((z) => (
        <group key={z}>
          {[-1.43, 1.43].map((x) => (
            <group key={x} position={[x, -0.04, z]}>
              <mesh>
                <boxGeometry args={[0.09, 1.05, 0.8]} />
                <meshStandardMaterial color="#0f172a" metalness={0.45} roughness={0.28} />
              </mesh>
              {[-0.195, 0.195].map((doorOffset) => (
                <mesh key={doorOffset} position={[x < 0 ? -0.05 : 0.05, 0, doorOffset]}>
                  <boxGeometry args={[0.11, 0.93, 0.36]} />
                  <meshStandardMaterial color="#d3dbe3" metalness={0.64} roughness={0.25} />
                </mesh>
              ))}
              <mesh position={[x < 0 ? -0.06 : 0.06, -0.29, 0]}>
                <boxGeometry args={[0.12, 0.2, 0.8]} />
                <meshStandardMaterial color="#d93f42" metalness={0.42} roughness={0.26} />
              </mesh>
            </group>
          ))}
        </group>
      ))}

      {[-3.15, 3.15].map((z) => (
        <group key={z} position={[0, -0.92, z]}>
          <mesh>
            <boxGeometry args={[2.25, 0.2, 1.12]} />
            <meshStandardMaterial color="#1e293b" metalness={0.7} roughness={0.42} />
          </mesh>
          {[-0.84, 0.84].map((x) => (
            <mesh key={x} position={[x, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
              <cylinderGeometry args={[0.42, 0.42, 0.18, 16]} />
              <meshStandardMaterial color="#111827" metalness={0.62} roughness={0.44} />
            </mesh>
          ))}
        </group>
      ))}
    </group>
  );
}

function Train() {
  const train = useRef<Group>(null);
  const scrollProgress = useRef(0);

  useEffect(() => {
    const updateScrollProgress = () => {
      const scrollableDistance = document.documentElement.scrollHeight - window.innerHeight;
      scrollProgress.current = scrollableDistance > 0 ? window.scrollY / scrollableDistance : 0;
    };

    updateScrollProgress();
    window.addEventListener("scroll", updateScrollProgress, { passive: true });
    return () => window.removeEventListener("scroll", updateScrollProgress);
  }, []);

  useFrame((_, delta) => {
    if (!train.current) return;

    const scrollPosition = Math.min(Math.max(scrollProgress.current, 0), 1);
    // Starts briskly, but never reaches the end before the page scroll does.
    const progress = Math.pow(scrollPosition, 0.7);
    const targetZ = -28 + progress * 31;
    // Follow the same angled centreline used by the rail bed at every depth.
    const targetX = trackOffsetForZ(targetZ);

    train.current.position.z = MathUtils.damp(train.current.position.z, targetZ, 4, delta);
    train.current.position.x = MathUtils.damp(train.current.position.x, targetX, 4, delta);
    train.current.rotation.y = MathUtils.damp(train.current.rotation.y, 0.107, 4, delta);
  });

  return (
    <group ref={train} position={[0, -0.24, -28]}>
      <MRTCar />
      <PassengerCar position={[0, 0, -9.85]} />
      <PassengerCar position={[0, 0, -19.7]} />
    </group>
  );
}

function RailBed() {
  const sections = Array.from({ length: 16 }, (_, index) => {
    const z = -48 + index * 4.5;
    return { z, x: trackOffsetForZ(z) };
  });

  return (
    <group rotation={[0, TRACK_ANGLE, 0]}>
      {sections.map(({ x, z }) => (
        <group key={z} position={[x, -1.65, z]} rotation={[0, 0.107, 0]}>
          <mesh position={[0, -0.17, 0]}>
            <boxGeometry args={[4.6, 0.16, 4.85]} />
            <meshStandardMaterial color="#172033" roughness={0.95} />
          </mesh>
          {[-0.82, 0.82].map((railX) => (
            <group key={railX} position={[railX, 0, 0]}>
              <mesh position={[0, -0.07, 0]}>
                <boxGeometry args={[0.25, 0.06, 4.85]} />
                <meshStandardMaterial color="#64748b" metalness={0.82} roughness={0.34} />
              </mesh>
              <mesh position={[0, 0.02, 0]}>
                <boxGeometry args={[0.1, 0.12, 4.85]} />
                <meshStandardMaterial color="#cbd5e1" metalness={0.92} roughness={0.2} />
              </mesh>
            </group>
          ))}
          {[-1.65, 0, 1.65].map((sleeperZ) => (
            <mesh key={sleeperZ} position={[0, -0.18, sleeperZ]}>
              <boxGeometry args={[3.35, 0.13, 0.34]} />
              <meshStandardMaterial color="#475569" metalness={0.28} roughness={0.8} />
            </mesh>
          ))}
        </group>
      ))}
    </group>
  );
}

export function TrainScene() {
  return (
    <Canvas camera={{ position: [0, 2, 8], fov: 48 }} dpr={[1, 1.5]} gl={{ alpha: true, antialias: true }}>
      <ambientLight intensity={0.42} />
      <directionalLight position={[4, 6, 5]} intensity={2.5} color="#dbeafe" />
      <fog attach="fog" args={["#020617", 14, 55]} />
      <RailBed />
      <group rotation={[0, TRACK_ANGLE, 0]}>
        <Train />
      </group>
    </Canvas>
  );
}
