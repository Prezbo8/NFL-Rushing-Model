-- Injured players whose absence moves a grade, one dated snapshot per scrape.
-- `share` is the player's season-to-date slice of his unit (see injuries.py);
-- kept per snapshot so the injury grade can be back-tested later.

create table if not exists nfl_injury_impact (
    season      integer not null,
    scraped_on  date    not null,
    team        text    not null,
    unit        text    not null,   -- defense | ol | rb
    player      text    not null,
    position    text,
    status      text,
    share       numeric(6,4),
    primary key (season, scraped_on, team, unit, player)
);

-- same access model as nfl_rushing_team_stats: anon may read, never write
alter table nfl_injury_impact enable row level security;
drop policy if exists "anon read" on nfl_injury_impact;
create policy "anon read" on nfl_injury_impact for select to anon using (true);
revoke insert, update, delete on nfl_injury_impact from anon;
