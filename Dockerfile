FROM python:3.11-slim
 
# HuggingFace requires non-root user with uid 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
 
WORKDIR $HOME/app
 
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt
 
COPY --chown=user . .
 
# HuggingFace routes all traffic to port 7860
EXPOSE 7860
 
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
 