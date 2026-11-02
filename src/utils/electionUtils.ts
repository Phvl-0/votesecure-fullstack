import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, getSession } from "@/lib/api";
import type { ApiCandidate, ApiElection } from "@/lib/api";

export interface Candidate {
  id: string;
  election_id: string;
  name: string;
  party: string;
  bio: string;
  image?: string;
  created_at?: string;
  updated_at?: string;
}

export interface Election {
  id: string;
  title: string;
  description: string;
  start_date: string;
  end_date: string;
  status: string;
  total_votes: number;
  image?: string;
  created_at?: string;
  updated_at?: string;
  candidates?: Candidate[];
}

export interface Vote {
  id?: string;
  election_id: string;
  candidate_id: string;
  user_id?: string;
  created_at?: string;
}

// --- API shapes -> the shapes the pages already use ---
const toCandidate = (c: ApiCandidate, electionId: string): Candidate => ({
  id: c.id,
  election_id: c.election_id ?? electionId,
  name: c.name,
  party: c.party ?? "",
  bio: c.bio ?? "",
  image: c.image ?? undefined,
});

const toElection = (e: ApiElection, totalVotes: number): Election => ({
  id: e.id,
  title: e.title,
  description: e.description ?? "",
  start_date: e.start_date,
  end_date: e.end_date,
  status: e.status,
  total_votes: totalVotes,
  candidates: e.candidates.map((c) => toCandidate(c, e.id)),
});

// The API has no stored vote counter: totals come from /results, which counts the votes.
// Upcoming elections are not in /results, so they get 0.
const fetchElections = async (): Promise<Election[]> => {
  const [elections, results] = await Promise.all([api.listElections(), api.getResults()]);
  const totals = new Map<string, number>(
    results.map((r): [string, number] => [r.id, r.total_votes])
  );
  return elections.map((e) => toElection(e, totals.get(e.id) ?? 0));
};

// There is no single-election endpoint yet, so pick it from the list.
const fetchElection = async (id: string): Promise<Election | null> => {
  const elections = await fetchElections();
  return elections.find((e) => e.id === id) ?? null;
};

const addElection = async (
  election: Omit<Election, "id" | "total_votes" | "created_at" | "updated_at">
): Promise<Election> => {
  const created = await api.createElection({
    title: election.title,
    description: election.description,
    start_date: election.start_date,
    end_date: election.end_date,
  });
  return toElection(created, 0);
};

const deleteElection = async (id: string): Promise<void> => {
  await api.deleteElection(id);
};

const addCandidate = async ({
  electionId,
  candidate,
}: {
  electionId: string;
  candidate: Omit<Candidate, "id" | "election_id" | "created_at" | "updated_at">;
}): Promise<Candidate> => {
  const created = await api.addCandidate(electionId, {
    name: candidate.name,
    party: candidate.party,
    bio: candidate.bio,
    image: candidate.image,
  });
  return toCandidate(created, electionId);
};

// The API only needs the candidate id; electionId stays in the signature for the callers.
const deleteCandidate = async ({
  candidateId,
}: {
  electionId: string;
  candidateId: string;
}): Promise<void> => {
  await api.deleteCandidate(candidateId);
};

// The voter is the person in the token; the browser never says who is voting.
const castVote = async ({
  electionId,
  candidateId,
}: {
  electionId: string;
  candidateId: string;
}): Promise<void> => {
  await api.castVote(electionId, candidateId);
};

const checkIfUserVoted = async (electionId: string): Promise<boolean> => {
  if (!getSession()) return false;
  return api.hasVoted(electionId);
};

// --- Hooks: same names, same cache keys as before ---
export const useElections = () => {
  return useQuery({
    queryKey: ["elections"],
    queryFn: fetchElections,
    // Replaces the old live-update channel: refresh every 15 seconds.
    refetchInterval: 15000,
  });
};

export const useElection = (id: string | undefined) => {
  return useQuery({
    queryKey: ["election", id],
    queryFn: () => fetchElection(id as string),
    enabled: !!id,
  });
};

export const useAddElection = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: addElection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["elections"] });
    },
  });
};

export const useDeleteElection = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteElection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["elections"] });
    },
  });
};

export const useAddCandidate = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: addCandidate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["elections"] });
    },
  });
};

export const useDeleteCandidate = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteCandidate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["elections"] });
    },
  });
};

export const useCastVote = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: castVote,
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["elections"] });
      queryClient.invalidateQueries({ queryKey: ["election", variables.electionId] });
      queryClient.invalidateQueries({ queryKey: ["hasVoted", variables.electionId] });
      queryClient.invalidateQueries({ queryKey: ["electionResults"] });
    },
  });
};

export const useHasVoted = (electionId: string | undefined) => {
  return useQuery({
    queryKey: ["hasVoted", electionId],
    queryFn: () => checkIfUserVoted(electionId as string),
    enabled: !!electionId,
  });
};
