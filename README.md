ローカルネットワークにある複数のSupervisorを一括監視する簡易ツール

# how to build
docker build -t managed_supervisors .

# how to run
docker run -p 5000:5000 managed_supervisors
