#!/usr/bin/env python3
"""Build index.html from the fragments in src/.

Edit src/head.html (styles) and src/body.html (markup + logic), then run this.
Never edit index.html directly -- it is generated and will be overwritten.
"""
import pathlib, json, re
sc = pathlib.Path(__file__).parent
repo = sc.parent
head=(sc/"head.html").read_text(); body=(sc/"body.html").read_text()
logos=(sc/"logos_data.json").read_text(); nfl=(sc/"nfl_logo.json").read_text().strip(); colors=(sc/"colors.json").read_text().replace("\n","")
colors2=(sc/"colors2.json").read_text().replace("\n","")
# anon key is public by design (read-only under RLS); it already ships in index.html
anon=re.search(r'SUPABASE_ANON="([^"]+)"', (repo/"index.html").read_text()).group(1)
data=json.load(open(sc/"matchup_data.json"))
meta={t:{"city":v["city"],"name":v["name"]} for t,v in data.items()}
fontlink=re.search(r'<link rel="stylesheet" href="https://fonts\.googleapis[^>]+>',head).group(0)
styles="\n".join(re.findall(r'<style>.*?</style>',head,re.S))
mk=body.index("<script>")
markup, script = body[:mk], body[mk+len("<script>"):body.rindex("</script>")]

# ---- live page (GitHub Pages): fetches Supabase ----
live_script = script.replace(
  'const NAMES = Object.fromEntries(Object.entries(DATA).map(([k,v])=>[k, v.city+" "+v.name]));',
  'const NAMES = Object.fromEntries(Object.entries(DATA).map(([k,v])=>[k, META[k].city+" "+META[k].name]));'
).replace('DATA[t].name.toLowerCase()','META[t].name.toLowerCase()')

COLS = ("team,side,games,attempts,rushing_yards,ypc,rushing_tds,first_downs,long_run,dvoa,succ_pct,"
        "epa_att,aybco,ayaco,stf_pct,exp_pct,crt_pct,aryoe,ply_gm,rush_pct,yd_ply,pt_gm,drv_gm,sec_ply,scraped_on,scraped_at")

live = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NFL Rushing Model</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%270%200%2064%2064%27%3E%3Crect%20width%3D%2764%27%20height%3D%2764%27%20rx%3D%2714%27%20fill%3D%27%23111B1F%27%2F%3E%3Cg%20transform%3D%27rotate%28-30%2032%2032%29%27%3E%3Cpath%20d%3D%27M5%2032Q32%207%2059%2032Q32%2057%205%2032Z%27%20fill%3D%27%239A5324%27%20stroke%3D%27%2361300F%27%20stroke-width%3D%271.6%27%2F%3E%3Cpath%20d%3D%27M21%2032h22%27%20fill%3D%27none%27%20stroke%3D%27%23F6F1E8%27%20stroke-width%3D%273.2%27%20stroke-linecap%3D%27round%27%2F%3E%3Cg%20stroke%3D%27%23F6F1E8%27%20stroke-width%3D%273%27%20stroke-linecap%3D%27round%27%3E%3Cpath%20d%3D%27M26%2027v10%27%2F%3E%3Cpath%20d%3D%27M32%2026.2v11.6%27%2F%3E%3Cpath%20d%3D%27M38%2027v10%27%2F%3E%3C%2Fg%3E%3C%2Fg%3E%3C%2Fsvg%3E">
<meta name="description" content="NFL Rushing Model — NFL rushing offense vs rushing defense, live from FTN data.">
{fontlink}
<style>:root{{color-scheme:light dark}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
{styles}
<style>
#boot{{padding:60px 0;text-align:center;color:var(--muted);font-family:"Public Sans",system-ui,sans-serif}}
#boot b{{display:block;font-family:"Archivo",system-ui,sans-serif;font-size:19px;color:var(--ink);margin-bottom:7px}}
#boot code{{font-size:12.5px;color:var(--faint)}}
</style>
</head>
<body>
<div id="boot"><b>Loading team data…</b><span>reading the latest snapshot from Supabase</span></div>
<div id="app" hidden>
{markup}</div>
<script>
const LOGOS={logos};
const NFL_LOGO={nfl};
const COLORS={colors};
const COLORS2={colors2};
const META={json.dumps(meta,separators=(',',':'))};
const SUPABASE_URL="https://mfliuasrygxkembqmrkr.supabase.co";
const SUPABASE_ANON="{anon}";   // anon key: read-only, enforced by row-level security

async function sb(path){{
  const r=await fetch(`${{SUPABASE_URL}}/rest/v1/${{path}}`,
    {{headers:{{apikey:SUPABASE_ANON,Authorization:"Bearer "+SUPABASE_ANON}}}});
  if(!r.ok) throw new Error("Supabase returned "+r.status+" for "+path.split("?")[0]);
  return r.json();
}}

async function loadData(){{
  const r=await fetch(`${{SUPABASE_URL}}/rest/v1/nfl_rushing_latest?select={COLS}`,
    {{headers:{{apikey:SUPABASE_ANON,Authorization:"Bearer "+SUPABASE_ANON}}}});
  if(!r.ok) throw new Error("Supabase returned "+r.status);
  const rows=await r.json();
  if(!rows.length) throw new Error("no rows returned");
  const out={{}};
  for(const x of rows){{ (out[x.team] ??= {{}})[x.side]=x; }}
  const bad=Object.entries(out).filter(([,v])=>!v.offense||!v.defense).map(([k])=>k);
  if(bad.length) throw new Error("incomplete data for "+bad.join(", "));
  return out;
}}

(async function boot(){{
  let DATA, GAMES=[], RBS=[];
  try{{
    DATA=await loadData();
    // game logs are a nice-to-have: a failure here must not blank the page
    try{{
      [GAMES,RBS]=await Promise.all([
        sb("nfl_game_logs?select=week,team,opponent,carries,rush_yards,rush_tds,ypc,points_for,points_against&order=week.desc"),
        sb("nfl_rb_game_logs?select=week,team,opponent,player,position,carries,rush_yards,rush_tds")]);
    }}catch(e){{ console.warn("game logs unavailable:",e.message); }}
  }}
  catch(err){{
    document.getElementById("boot").innerHTML =
      `<b>Couldn't load the data.</b><span>${{err.message}}</span><br>`+
      `<code>The scraper runs Sun, Tue and Wed. If this persists, check the Actions tab.</code>`;
    return;
  }}
  document.getElementById("boot").hidden=true;
  document.getElementById("app").hidden=false;
{live_script}
}})();
</script>
</body>
</html>
"""
(repo/"index.html").write_text(live)

print(f"index.html rebuilt: {len(live)//1024} KB")
