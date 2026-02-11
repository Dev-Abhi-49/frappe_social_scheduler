FROM frappe/erpnext-worker:version-15

USER root
RUN apt-get update && apt-get install -y ffmpeg
USER frappe
