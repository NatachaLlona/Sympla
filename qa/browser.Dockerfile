FROM mcr.microsoft.com/playwright:v1.64.1-noble
WORKDIR /qa
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN npm init -y && npm install --save-exact playwright@1.64.1
COPY qa/frontend_browser_test.cjs /qa/test.cjs
COPY qa/map_browser_test.cjs /qa/map-test.cjs
COPY qa/workspace_browser_test.cjs /qa/workspace-test.cjs
CMD ["node", "/qa/test.cjs"]
