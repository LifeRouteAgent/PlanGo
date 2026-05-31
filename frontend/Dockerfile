FROM node:20-alpine

WORKDIR /app

COPY package*.json /app/
RUN npm install

COPY . /app

EXPOSE 5173

CMD ["sh", "-c", "node -e \"const fs=require('fs'); const cfg={amap_key:process.env.AMAP_API_KEY||'', amap_security_js_code:process.env.AMAP_SECURITY_JS_CODE||''}; fs.writeFileSync('/app/public/app-config.json', JSON.stringify(cfg, null, 2));\" && npm run dev -- --host 0.0.0.0 --port 5173"]
