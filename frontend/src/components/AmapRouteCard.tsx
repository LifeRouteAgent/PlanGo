import { Maximize2, Minus, Plus, Route } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { isAmapConfigured, loadAmap } from "../lib/amap";
import type { Plan, RouteSegment } from "../types/agent";

interface AmapRouteCardProps {
  plan: Plan;
  large?: boolean;
  onOpenFullMap?: () => void;
}

type AMapAny = any;

const segmentLabels: Record<string, string> = {
  all: "全部路线",
  travel: "出行",
  activity: "活动",
  meal: "餐饮",
  return: "返程"
};

function getSegments(plan: Plan): RouteSegment[] {
  if (plan.route?.segments?.length) {
    return plan.route.segments;
  }
  return [
    {
      type: "travel",
      title: "完整路线",
      color: "#5b6cff",
      polyline: plan.route?.polyline ?? []
    }
  ];
}

function toLngLat(point: { lat: number; lng: number }) {
  return [point.lng, point.lat];
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function markerTimeText(start?: string, end?: string) {
  if (start && end && start !== "--:--" && end !== "--:--") {
    return `${start}-${end}`;
  }
  if (start && start !== "--:--") {
    return start;
  }
  return "时间待确认";
}

export function AmapRouteCard({ plan, large = false, onOpenFullMap }: AmapRouteCardProps) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<AMapAny>(null);
  const [activeSegment, setActiveSegment] = useState("all");
  const [status, setStatus] = useState<string | null>(null);
  const segments = useMemo(() => getSegments(plan), [plan]);
  const visibleSegments = useMemo(
    () => (activeSegment === "all" ? segments : segments.filter((item) => item.type === activeSegment)),
    [activeSegment, segments]
  );
  const configured = isAmapConfigured();

  useEffect(() => {
    if (!configured || !mapRef.current) {
      return;
    }

    let disposed = false;

    async function drawMap() {
      try {
        const AMap = (await loadAmap()) as AMapAny;
        if (disposed || !mapRef.current) {
          return;
        }

        mapInstanceRef.current?.destroy?.();
        const firstPoint =
          visibleSegments.flatMap((segment) => segment.polyline)[0] ??
          plan.route?.stops.find((stop) => stop.location)?.location;

        const map = new AMap.Map(mapRef.current, {
          zoom: 13,
          center: firstPoint ? [firstPoint.lng, firstPoint.lat] : [116.480, 39.996],
          viewMode: "2D",
          mapStyle: "amap://styles/normal",
          features: ["bg", "road", "building", "point"],
          resizeEnable: true
        });
        mapInstanceRef.current = map;

        if (AMap.ToolBar) {
          map.addControl(new AMap.ToolBar({ position: "RB" }));
        }
        if (AMap.Scale) {
          map.addControl(new AMap.Scale());
        }

        const bounds: AMapAny[] = [];
        visibleSegments.forEach((segment) => {
          const path = segment.polyline.map(toLngLat);
          path.forEach((point) => bounds.push(point));
          if (path.length > 1) {
            const polyline = new AMap.Polyline({
              path,
              strokeColor: segment.color,
              strokeWeight: large ? 8 : 6,
              strokeOpacity: 0.92,
              lineJoin: "round",
              lineCap: "round"
            });
            map.add(polyline);
          }
        });

        const infoWindow = new AMap.InfoWindow({
          offset: new AMap.Pixel(0, -36),
          closeWhenClickMap: true
        });

        plan.route?.stops.forEach((stop) => {
          if (!stop.location) {
            return;
          }
          const safeTitle = escapeHtml(stop.title);
          const safeAddress = escapeHtml(stop.location.address ?? "");
          const safeTime = escapeHtml(markerTimeText(stop.start_time, stop.end_time));
          const marker = new AMap.Marker({
            position: [stop.location.lng, stop.location.lat],
            title: stop.title,
            zIndex: 100 + stop.order,
            content: `
              <div class="amap-stop-marker">
                <div class="amap-stop-index">${stop.order}</div>
                <div class="amap-stop-bubble">
                  <strong>${safeTitle}</strong>
                  <span>${safeTime}</span>
                </div>
              </div>
            `,
            offset: new AMap.Pixel(-16, -36)
          });
          marker.on("click", () => {
            infoWindow.setContent(`
              <div class="amap-info-window">
                <strong>${safeTitle}</strong>
                <span>${safeTime}</span>
                <small>${safeAddress}</small>
              </div>
            `);
            infoWindow.open(map, [stop.location!.lng, stop.location!.lat]);
          });
          map.add(marker);
          bounds.push([stop.location.lng, stop.location.lat]);
        });

        if (bounds.length > 1) {
          map.setFitView();
        }
        setStatus(null);
      } catch (error) {
        setStatus((error as Error).message);
      }
    }

    void drawMap();

    return () => {
      disposed = true;
      mapInstanceRef.current?.destroy?.();
      mapInstanceRef.current = null;
    };
  }, [activeSegment, configured, large, plan, visibleSegments]);

  return (
    <article className={`route-card amap-route-card ${large ? "is-large" : ""}`}>
      <div className="panel-title-row">
        <div>
          <h2>路线概览</h2>
          <p>真实地图、地点标注与高德路线</p>
        </div>
        {onOpenFullMap && (
          <button type="button" onClick={onOpenFullMap}>
            查看完整地图 <Maximize2 size={15} />
          </button>
        )}
      </div>

      <div className="route-switcher" aria-label="切换路线">
        {["all", "travel", "activity", "meal", "return"].map((type) => (
          <button
            type="button"
            className={activeSegment === type ? "is-active" : ""}
            key={type}
            onClick={() => setActiveSegment(type)}
          >
            {segmentLabels[type]}
          </button>
        ))}
      </div>

      <div className="amap-container" ref={mapRef}>
        {!configured && (
          <div className="map-config-state">
            <Route size={26} />
            <strong>高德地图未配置</strong>
            <p>请在前端环境变量中设置 VITE_AMAP_JS_KEY，必要时设置 VITE_AMAP_SECURITY_CODE。</p>
          </div>
        )}
        {configured && status && (
          <div className="map-config-state">
            <Route size={26} />
            <strong>高德地图加载失败</strong>
            <p>{status}</p>
          </div>
        )}
      </div>

      <div className="map-controls-hint" aria-hidden="true">
        <button type="button">
          <Plus size={16} />
        </button>
        <button type="button">
          <Minus size={16} />
        </button>
      </div>
    </article>
  );
}
