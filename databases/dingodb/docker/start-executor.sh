#!/bin/bash

ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && cd .. && pwd )"
JAR_PATH=$(find "$ROOT" -name 'dingo-executor-*.jar')
LOCAL_STORE_JAR_PATH=$(find "$ROOT" -name 'dingo-store-local*.jar')
NET_JAR_PATH=$(find "$ROOT" -name 'dingo-net-*.jar')
APP_HOME=$( cd "$( dirname "$0" )/.." && pwd )
PLATFORM=$(uname -s)-$(uname -m | sed 's/x86_64/x64/')
LOG_DIR="$ROOT/log"

if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
fi

EXECUTOR_XMS=${DINGO_EXECUTOR_XMS:-32g}
EXECUTOR_XMX=${DINGO_EXECUTOR_XMX:-32g}
EXECUTOR_SOFT_MAX_HEAP=${DINGO_EXECUTOR_SOFT_MAX_HEAP:-$EXECUTOR_XMX}
EXECUTOR_MAX_DIRECT_MEMORY=${DINGO_EXECUTOR_MAX_DIRECT_MEMORY:-4096m}

JAVA_OPTS="\
    -Xms${EXECUTOR_XMS} -Xmx${EXECUTOR_XMX} \
    -XX:+UseZGC \
    -XX:SoftMaxHeapSize=${EXECUTOR_SOFT_MAX_HEAP} \
    -XX:ZAllocationSpikeTolerance=5 \
    -XX:+ZProactive \
    -XX:ZCollectionInterval=4 \
    -XX:+UseLargePages \
    -XX:+UseNUMA \
    -XX:+ParallelRefProcEnabled \
    -XX:+AlwaysPreTouch \
    -XX:+DisableExplicitGC \
    -XX:+HeapDumpOnOutOfMemoryError \
    -XX:MaxDirectMemorySize=${EXECUTOR_MAX_DIRECT_MEMORY} \
    -XX:ReservedCodeCacheSize=256m \
    -XX:+UseCodeCacheFlushing \
    -XX:+TieredCompilation \
    -XX:TieredStopAtLevel=4 \
    -XX:InitialCodeCacheSize=256m \
    -Xlog:gc*:file=${LOG_DIR}/gc.log:time:filecount=5,filesize=100M \
"

EMBEDDED_JDK="${APP_HOME}/${PLATFORM}"
if [ -d "${EMBEDDED_JDK}" ]; then
    export JAVA_HOME="${EMBEDDED_JDK}"
    PATH="${JAVA_HOME}/bin:${PATH}"
fi

${JAVA_HOME}/bin/java ${JAVA_OPTS} \
     --add-opens java.base/java.util=ALL-UNNAMED \
     --add-opens java.base/java.lang=ALL-UNNAMED \
     -Dlogback.configurationFile=file:${ROOT}/conf/logback-executor.xml \
     -classpath ${JAR_PATH}:${NET_JAR_PATH}:${LOCAL_STORE_JAR_PATH} \
     io.dingodb.server.executor.Starter \
     --config ${ROOT}/conf/executor.yaml \
     > ${ROOT}/log/executor.out
