let amapPromise: Promise<unknown> | null = null;
let configPromise: Promise<AmapPublicConfig> | null = null;

interface AmapPublicConfig {
  amap_key?: string;
  amapJsKey?: string;
  amap_security_js_code?: string;
  amapSecurityCode?: string;
}

declare global {
  interface Window {
    AMap?: unknown;
    _AMapSecurityConfig?: {
      securityJsCode: string;
    };
  }
}

async function loadPublicConfig() {
  if (configPromise) {
    return configPromise;
  }

  configPromise = (async () => {
    const candidates = ["/app-config.json", "/trip/client-config"];
    for (const url of candidates) {
      try {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) {
          continue;
        }
        const payload = (await response.json()) as AmapPublicConfig;
        if (payload.amap_key || payload.amapJsKey) {
          return payload;
        }
      } catch {
        // 公开配置读取失败时继续尝试下一个来源。
      }
    }
    return {
      amap_key: import.meta.env.VITE_AMAP_JS_KEY as string | undefined,
      amap_security_js_code: import.meta.env.VITE_AMAP_SECURITY_CODE as string | undefined
    };
  })();

  return configPromise;
}

export async function getAmapKey() {
  const config = await loadPublicConfig();
  return config.amap_key || config.amapJsKey;
}

export async function getAmapSecurityCode() {
  const config = await loadPublicConfig();
  return config.amap_security_js_code || config.amapSecurityCode;
}

export async function isAmapConfigured() {
  return Boolean(await getAmapKey());
}

export async function loadAmap() {
  const key = await getAmapKey();
  if (!key) {
    return Promise.reject(new Error("高德地图未配置：请检查 frontend/public/app-config.json。"));
  }

  if (window.AMap) {
    return Promise.resolve(window.AMap);
  }

  if (amapPromise) {
    return amapPromise;
  }

  const securityCode = await getAmapSecurityCode();
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
