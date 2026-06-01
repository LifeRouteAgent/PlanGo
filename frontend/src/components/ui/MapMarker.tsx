interface MapMarkerProps {
  label: string;
  title: string;
  time: string;
  active?: boolean;
}

export function MapMarker({ label, title, time, active = false }: MapMarkerProps) {
  return (
    <div className={`map-marker-shell ${active ? "is-active" : ""}`}>
      <div className="map-marker-index">{label}</div>
      <div className="map-marker-copy">
        <strong>{title}</strong>
        <span>{time}</span>
      </div>
    </div>
  );
}
