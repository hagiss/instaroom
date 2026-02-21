"use client";

import { useEffect, useRef, useCallback } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { SplatMesh } from "@sparkjsdev/spark";
import type { ViewerData } from "@/lib/types";

interface SplatCanvasProps {
  viewerData: ViewerData;
  onLoaded?: () => void;
}

export function SplatCanvas({ viewerData, onLoaded }: SplatCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const frameIdRef = useRef<number>(0);
  const onLoadedRef = useRef(onLoaded);
  useEffect(() => {
    onLoadedRef.current = onLoaded;
  }, [onLoaded]);

  const resetView = useCallback(() => {
    if (!controlsRef.current) return;
    const controls = controlsRef.current;
    const [px, py, pz] = viewerData.camera_position;
    const [tx, ty, tz] = viewerData.camera_target;
    controls.object.position.set(px, py, pz);
    controls.target.set(tx, ty, tz);
    controls.update();
  }, [viewerData]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(
      60,
      container.clientWidth / container.clientHeight,
      0.1,
      1000,
    );
    const [px, py, pz] = viewerData.camera_position;
    camera.position.set(px, py, pz);

    const renderer = new THREE.WebGLRenderer({
      antialias: false,
      alpha: true,
    });
    const pixelRatio = Math.min(window.devicePixelRatio, 2);
    renderer.setPixelRatio(pixelRatio);
    renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    const [tx, ty, tz] = viewerData.camera_target;
    controls.target.set(tx, ty, tz);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minPolarAngle = Math.PI * 0.1;
    controls.maxPolarAngle = Math.PI * 0.85;
    controls.minDistance = 0.5;
    controls.maxDistance = 10;
    controls.touches = {
      ONE: THREE.TOUCH.ROTATE,
      TWO: THREE.TOUCH.DOLLY_PAN,
    };
    controls.update();
    controlsRef.current = controls;

    const splat = new SplatMesh({
      url: viewerData.splat_url,
      onLoad: () => {
        onLoadedRef.current?.();
      },
    });
    scene.add(splat);

    function animate() {
      frameIdRef.current = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    function handleResize() {
      if (!container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    window.addEventListener("resize", handleResize);

    return () => {
      cancelAnimationFrame(frameIdRef.current);
      window.removeEventListener("resize", handleResize);
      controls.dispose();
      renderer.dispose();
      splat.dispose();
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [viewerData]);

  // Expose resetView for ViewerControls
  useEffect(() => {
    const container = containerRef.current;
    if (container) {
      (container as HTMLDivElement & { resetView?: () => void }).resetView =
        resetView;
    }
  }, [resetView]);

  return (
    <div
      ref={containerRef}
      data-splat-container
      className="h-full w-full touch-none"
    />
  );
}
