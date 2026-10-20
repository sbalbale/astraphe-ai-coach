# Build from this directory:  docker build -t astraphe-photon-bridge photon-bridge
# Run exactly ONE replica: the Photon gRPC stream has a single consumer.
FROM node:20-slim

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY index.mjs lib.mjs ./

ENV PORT=8790
EXPOSE 8790
USER node
CMD ["node", "index.mjs"]
