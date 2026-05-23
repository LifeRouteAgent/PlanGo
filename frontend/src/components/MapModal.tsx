import { X } from "lucide-react";
import { AmapRouteCard } from "./AmapRouteCard";
import type { Plan } from "../types/agent";

interface MapModalProps {
  plan: Plan | null;
  onClose: () => void;
}

export function MapModal({ plan, onClose }: MapModalProps) {
  if (!plan) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="完整地图">
      <div className="map-modal">
        <header>
          <div>
            <p className="eyebrow">高德地图</p>
            <h2>完整路线</h2>
          </div>
          <button type="button" className="icon-button" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <AmapRouteCard plan={plan} large />
      </div>
    </div>
  );
}
