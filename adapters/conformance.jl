#!/usr/bin/env julia
# Otwin conformance adapter for Julia.
#
# Reads one fixture on stdin, writes one result document on stdout.
# It reports NUMBERS ONLY and never judges itself — all judgement happens in
# otwin-spec, so a bug in Julia cannot hide a bug in Julia's models.
#
#   otwin-conformance "julia --project=. adapters/conformance.jl" --name julia
#
# Fill in `build_model` and `simulate` against Otwin.jl. Anything not yet
# implemented should be pushed onto `unsupported` — a declared gap is honest
# and does not block conformance; a wrong answer does.

using JSON3

function build_model(kind::String, p::Dict)
    if kind == "dc_motor"
        L, Jm = get(p, "L", 0.5), get(p, "inertia", 0.01)
        Re, b, K = get(p, "Re", 1.0), get(p, "b", 0.1), get(p, "K", 0.5)
        H      = x -> 0.5x[1]^2 / L + 0.5x[2]^2 / Jm
        grad_H = x -> [x[1] / L, x[2] / Jm]
        J      = x -> [0.0 -K; K 0.0]
        R      = x -> [Re 0.0; 0.0 b]
        g      = x -> reshape([1.0, 0.0], 2, 1)
        return (; H, grad_H, J, R, g, n_states = 2, n_inputs = 1, sigma = nothing)
    end
    error("model_kind $kind not implemented")
end

rhs(m, x, u) = (m.J(x) .- m.R(x)) * m.grad_H(x) .+ m.g(x) * u

function simulate(m, x0, t, U)          # classical RK4
    n = length(t); X = zeros(n, m.n_states); X[1, :] = x0
    for i in 1:(n - 1)
        dt = t[i + 1] - t[i]; x = X[i, :]; u = U[i, :]
        k1 = rhs(m, x, u); k2 = rhs(m, x .+ 0.5dt .* k1, u)
        k3 = rhs(m, x .+ 0.5dt .* k2, u); k4 = rhs(m, x .+ dt .* k3, u)
        X[i + 1, :] = x .+ (dt / 6) .* (k1 .+ 2k2 .+ 2k3 .+ k4)
    end
    X, [m.H(X[i, :]) for i in 1:n]
end

function run(fx)
    sc = fx["scenario"]; out = Dict{String,Any}()
    # Keys beginning with "_" are documentation (units, notes), not parameters.
    params = Dict(String(k) => v for (k, v) in pairs(fx["parameters"]) if !startswith(String(k), "_"))
    m  = build_model(fx["model_kind"], params)
    if haskey(sc, "sample_states")
        S = [Float64.(s) for s in sc["sample_states"]]
        out["matrices"] = Dict("J" => [m.J(x) for x in S], "R" => [m.R(x) for x in S])
        out["energy"]   = [m.H(x) for x in S]
        out["state"]    = S
    end
    if haskey(sc, "x0")
        ts = sc["t"]; t = range(ts["start"], ts["stop"], length = ts["num"]) |> collect
        U  = if get(get(sc, "u", Dict()), "kind", "zeros") == "constant"
                repeat(reshape(Float64.(sc["u"]["value"]), 1, :), length(t), 1)
             else zeros(length(t), m.n_inputs) end
        X, E = simulate(m, Float64.(sc["x0"]), t, U)
        out["t"] = t; out["state"] = [X[i, :] for i in 1:size(X, 1)]; out["energy"] = E
        out["matrices"] = get(out, "matrices", Dict("J" => [m.J(X[1, :])], "R" => [m.R(X[1, :])]))
    end
    out
end

fx = JSON3.read(read(stdin, String), Dict)
res = Dict("fixture_id" => fx["id"], "implementation" => "julia",
           "version" => "0.1.0", "unsupported" => String[], "outputs" => Dict())
try
    res["outputs"] = run(fx)
catch e
    res["unsupported"] = [fx["id"]]
    res["note"] = sprint(showerror, e)
end
JSON3.write(stdout, res)
