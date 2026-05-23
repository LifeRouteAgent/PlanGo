let amapPromise: Promise<unknown> | null = null;

declare global {
  interface Window {
    AMap?: unknown;
    _AMapSecurityConfig?: {
      securityJsCode: string;
    };
  }
}

export function getAmapKey() {
  return import.meta.env.VITE_AMAP_JS_KEY as string | undefined;
}

export function getAmapSecurityCode() {
  return import.meta.env.VITE_AMAP_SECURITY_CODE as string | undefined;
}

export function isAmapConfigured() {
  return Boolean(getAmapKey());
}

export function loadAmap() {
  const key = getAmapKey();
  if (!key) {
    return Promise.reject(new Error("高德地图未配置：请设置 VITE_AMAP_JS_KEY。"));
  }

  if (window.AMap) {
    return Promise.resolve(window.AMap);
  }

  if (amapPromise) {
    return amapPromise;
  }

  const securityCode = getAmapSecurityCode();
  if (securityCode) {
    window._AMapSecurityConfig = { securityJsCode: securityCode };
  }

  amapPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}&plugin=AMap.ToolBar,AMap.Scale`;
    script.async = true;
    script.onload = () => resolve(window.AMap);
    script.onerror = () => reject(new Error("高德地图脚本加载失败。"));
    document.head.appendChild(script);
  });

  return amapPromise;
}
