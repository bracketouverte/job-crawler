/**
 * Bundled by jsDelivr using Rollup v4.62.2 and esbuild v0.28.1.
 * Original file: /npm/htm@3.1.1/dist/htm.module.js
 *
 * Do NOT use SRI with dynamically generated files! More information: https://www.jsdelivr.com/using-sri-with-dynamic-files
 */
var a=function(p,o,l,n){var s;o[0]=0;for(var u=1;u<o.length;u++){var g=o[u++],i=o[u]?(o[0]|=g?1:2,l[o[u++]]):o[++u];g===3?n[0]=i:g===4?n[1]=Object.assign(n[1]||{},i):g===5?(n[1]=n[1]||{})[o[++u]]=i:g===6?n[1][o[++u]]+=i+"":g?(s=p.apply(i,a(p,i,l,["",null])),n.push(s),i[0]?o[0]|=2:(o[u-2]=0,o[u]=s)):n.push(i)}return n},d=new Map;function w(p){var o=d.get(this);return o||(o=new Map,d.set(this,o)),(o=a(this,o.get(p)||(o.set(p,o=(function(l){for(var n,s,u=1,g="",i="",f=[0],v=function(t){u===1&&(t||(g=g.replace(/^\s*\n\s*|\s*\n\s*$/g,"")))?f.push(0,t,g):u===3&&(t||g)?(f.push(3,t,g),u=2):u===2&&g==="..."&&t?f.push(4,t,0):u===2&&g&&!t?f.push(5,0,!0,g):u>=5&&((g||!t&&u===5)&&(f.push(u,0,g,s),u=6),t&&(f.push(u,t,0,s),u=6)),g=""},c=0;c<l.length;c++){c&&(u===1&&v(),v(c));for(var m=0;m<l[c].length;m++)n=l[c][m],u===1?n==="<"?(v(),f=[f],u=3):g+=n:u===4?g==="--"&&n===">"?(u=1,g=""):g=n+g[0]:i?n===i?i="":g+=n:n==='"'||n==="'"?i=n:n===">"?(v(),u=1):u&&(n==="="?(u=5,s=g,g=""):n==="/"&&(u<5||l[c][m+1]===">")?(v(),u===3&&(f=f[0]),u=f,(f=f[0]).push(2,0,u),u=0):n===" "||n==="	"||n===`
`||n==="\r"?(v(),u=2):g+=n),u===3&&g==="!--"&&(u=4,f=f[0])}return v(),f})(p)),o),arguments,[])).length>1?o:o[0]}export{w as default};
