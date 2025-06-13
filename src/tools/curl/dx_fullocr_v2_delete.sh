
BASE_URL="https://ksin.dx-suite.com"
API_KEY="afea053a8ed4258a670ec4ba18731a541b77dbe0b8a5d3807b4eb611f338a5e20e27fc38589095f39b0a11405c06b77c558741b0d05a44cad0e4d03988fb86e2"
JOB_ID="b4c23ae1-4cbb-41cd-a41d-f2c771e8c743"

curl -X POST \
    $BASE_URL/wf/api/fullocr/v2/delete \
    -H "apikey:$API_KEY" \
    -H "Content-Type: application/json; charset=utf-8" \
    -d "{ \"fullOcrJobId\": \"$JOB_ID\" }"
