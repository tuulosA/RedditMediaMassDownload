"""
redditcommand.automatic_posts package initializer
"""

# Top media post scheduling (daily, weekly, etc.)
from .top_post_scheduler import TopPostScheduler

send_daily_top_post_command = TopPostScheduler.generate_command("TOP POST OF THE DAY", "day")
send_weekly_top_post_command = TopPostScheduler.generate_command("TOP POST OF THE WEEK", "week")
send_monthly_top_post_command = TopPostScheduler.generate_command("TOP POST OF THE MONTH", "month")
send_yearly_top_post_command = TopPostScheduler.generate_command("TOP POST OF THE YEAR", "year")
send_all_time_top_post_command = TopPostScheduler.generate_command("TOP POST OF ALL TIME", "all")

send_daily_top_post_job = TopPostScheduler.generate_job("TOP POST OF THE DAY", "day")
send_weekly_top_post_job = TopPostScheduler.generate_job("TOP POST OF THE WEEK", "week")
send_monthly_top_post_job = TopPostScheduler.generate_job("TOP POST OF THE MONTH", "month")
send_yearly_top_post_job = TopPostScheduler.generate_job("TOP POST OF THE YEAR", "year")

# Followed user monitoring
from .follow_user import FollowUserScheduler
