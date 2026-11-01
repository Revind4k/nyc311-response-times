-- One row per 311 request, typed, with an explicit verdict on whether its time-to-close is usable.
--
-- Every row is kept and classified rather than filtered, so the data-quality table in the
-- README is a count over `quality`, and the analysis reads only quality = 'ok'.
create or replace table requests as
with raw as (
    select r.*, m.pulled_at
    from read_csv('data/raw/*.csv.gz', all_varchar = true, filename = true) r
    join manifest m on m.file = regexp_extract(r.filename, '[^/]+$')
),
typed as (
    select
        unique_key::bigint                                   as request_id,
        created_date::timestamp                              as created_at,
        try_cast(closed_date as timestamp)                   as closed_at,
        pulled_at::timestamp                                 as pulled_at,
        agency,
        complaint_type,
        descriptor,
        status,
        nullif(incident_zip, '')                             as zip,
        nullif(borough, 'Unspecified')                       as borough,
        community_board,
        open_data_channel_type                               as channel
    from raw
)
select
    *,
    case
        when status = 'Closed' and closed_at is null                          then 'closed_without_date'
        when status = 'Closed' and closed_at < created_at                     then 'closed_before_created'
        when status = 'Closed' and closed_at > pulled_at                      then 'closed_in_future'
        else 'ok'
    end                                                       as quality,
    -- A status other than Closed means still open, even if a closed_date is filled in:
    -- some agencies write a target date into that column before the work is done.
    status = 'Closed'                                         as is_closed,
    case when status = 'Closed'
         then date_diff('second', created_at, closed_at) / 3600.0
         else date_diff('second', created_at, pulled_at) / 3600.0
    end                                                       as hours,
    status = 'Closed' and date_diff('second', created_at, closed_at) between 0 and 59
                                                              as instant_close
from typed;
