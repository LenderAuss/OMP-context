// Loopback-only provider used by the no-inference integration test.
export default function(pi) {
  const url=process.env.OMP_KIT_FIXTURE_URL;
  if(!url||!/^http:\/\/127\.0\.0\.1:\d+\/v1$/.test(url))throw new Error("Fixture provider must use loopback");
  pi.registerProvider("context-kit-fixture",{baseUrl:url,apiKey:"synthetic-local-fixture",api:"openai-completions",models:[{
    id:"fixture",name:"Local memory fixture",api:"openai-completions",reasoning:false,input:["text"],contextWindow:200000,maxTokens:2048,
    cost:{input:0,output:0,cacheRead:0,cacheWrite:0}
  }]});
}
