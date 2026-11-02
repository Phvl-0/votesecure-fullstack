
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";
import Layout from "@/components/Layout";
import { api, getSession } from "@/lib/api";
import { useToast } from "@/components/ui/use-toast";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CircleUser, Award, Users } from "lucide-react";

interface VoteResult {
  candidateId: string;
  candidateName: string;
  party: string;
  voteCount: number;
  color?: string;
}

interface ElectionResult {
  id: string;
  title: string;
  endDate: string;
  totalVotes: number;
  results: VoteResult[];
  status: string;
}

// Generate colors for the pie chart
const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8', '#82ca9d', '#ffc658', '#8dd1e1'];

const Results = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [selectedView, setSelectedView] = useState<'bar' | 'pie'>('bar');
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  useEffect(() => {
    const checkAuth = async () => {
      const session = getSession();
      
      if (!session) {
        toast({
          title: "Authentication required",
          description: "Please log in to view election results",
          variant: "destructive",
        });
        navigate("/login");
      }
    };

    checkAuth();
  }, [navigate, toast]);

  // Refresh the tallies every 15 seconds (replaces the old live-update channel).
  useEffect(() => {
    const timer = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['electionResults'] });
      setLastUpdated(new Date());
    }, 15000);
    return () => clearInterval(timer);
  }, [queryClient]);

  const fetchResults = async (): Promise<ElectionResult[]> => {
    // The server counts the votes, hides upcoming elections and puts live ones first.
    const rows = await api.getResults();
    return rows.map((row) => ({
      id: row.id,
      title: row.title,
      endDate: row.end_date,
      totalVotes: row.total_votes,
      status: row.status,
      results: row.results.map((r, index) => ({
        candidateId: r.candidate_id,
        candidateName: r.candidate_name,
        party: r.party ?? "",
        voteCount: r.vote_count,
        color: COLORS[index % COLORS.length],
      })),
    }));
  };

  const { data: electionResults = [], isLoading, error } = useQuery({
    queryKey: ['electionResults'],
    queryFn: fetchResults,
    refetchOnWindowFocus: true,
    refetchInterval: 5000, // Fallback polling so live tallies stay fresh
  });

  if (error) {
    console.error("Error fetching results:", error);
    toast({
      title: "Error",
      description: "Failed to load election results",
      variant: "destructive",
    });
  }

  const calculatePercentage = (votes: number, total: number) => {
    if (total === 0) return 0;
    return ((votes / total) * 100).toFixed(1);
  };

  const getWinner = (results: VoteResult[]) => {
    if (!results.length) return null;
    return results.reduce((prev, current) => 
      (prev.voteCount > current.voteCount) ? prev : current
    );
  };

  return (
    <Layout>
      <div className="container mx-auto py-6">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-3xl font-bold">Election Results</h1>
          <p className="text-sm text-muted-foreground">
            Live · updated {lastUpdated.toLocaleTimeString()}
          </p>
        </div>
        
        {isLoading ? (
          <div className="flex justify-center items-center h-64">
            <p className="text-gray-500">Loading results...</p>
          </div>
        ) : electionResults.length === 0 ? (
          <Card>
            <CardContent className="pt-6">
              <p className="text-center text-gray-500">No elections with results to display yet.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-8">
            {electionResults.map((election) => {
              const winner = getWinner(election.results);
              const isLive = election.status !== 'ended';
              
              return (
                <Card key={election.id} className="overflow-hidden">
                  <CardHeader className="bg-muted/30">
                    <div className="flex justify-between items-start">
                      <div>
                        <CardTitle className="text-2xl flex items-center gap-2">
                          {election.title}
                          {isLive && (
                            <span className="inline-flex items-center gap-1.5 rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs font-semibold text-destructive">
                              <span className="h-2 w-2 animate-pulse rounded-full bg-destructive" />
                              LIVE
                            </span>
                          )}
                        </CardTitle>
                        <p className="text-sm text-muted-foreground mt-1">
                          {isLive ? "Ends on " : "Ended on "}
                          {new Date(election.endDate).toLocaleDateString()}
                        </p>
                      </div>
                      <div className="bg-primary/10 text-primary px-3 py-1 rounded-full text-sm font-medium">
                        {election.totalVotes} {election.totalVotes === 1 ? 'vote' : 'votes'} cast
                      </div>
                    </div>
                  </CardHeader>
                  
                  <CardContent className="pt-6">
                    {winner && election.totalVotes > 0 && (
                      <div className="mb-6 p-4 border rounded-lg bg-yellow-50/50 border-yellow-200">
                        <div className="flex items-center gap-4">
                          <div className="p-3 rounded-full bg-yellow-100">
                            <Award className="h-6 w-6 text-yellow-600" />
                          </div>
                          <div>
                            <h3 className="font-bold text-lg">
                              {isLive ? "Currently leading: " : "Winner: "}
                              {winner.candidateName}
                            </h3>
                            <p className="text-muted-foreground">
                              {winner.party} · {winner.voteCount} votes ({calculatePercentage(winner.voteCount, election.totalVotes)}%)
                            </p>
                            {isLive && (
                              <p className="text-xs text-muted-foreground mt-1">
                                Provisional — results update in real time until voting closes.
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                    
                    <Tabs defaultValue="bar" className="w-full" onValueChange={(value) => setSelectedView(value as 'bar' | 'pie')}>
                      <div className="flex justify-between items-center mb-4">
                        <h3 className="font-semibold text-lg">
                          {isLive ? "Live Voting Results" : "Voting Results"}
                        </h3>
                        <TabsList>
                          <TabsTrigger value="bar">
                            <BarChart className="h-4 w-4 mr-2" />
                            Bar Chart
                          </TabsTrigger>
                          <TabsTrigger value="pie">
                            <CircleUser className="h-4 w-4 mr-2" />
                            Pie Chart
                          </TabsTrigger>
                        </TabsList>
                      </div>
                      
                      <TabsContent value="bar" className="space-y-4">
                        <div className="h-[300px] w-full mt-4">
                          <ResponsiveContainer width="100%" height="100%">
                            <BarChart
                              data={election.results.map(result => ({
                                name: result.candidateName,
                                party: result.party,
                                votes: result.voteCount,
                                percentage: calculatePercentage(result.voteCount, election.totalVotes)
                              }))}
                              margin={{ top: 10, right: 30, left: 0, bottom: 30 }}
                            >
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="name" angle={-45} textAnchor="end" height={70} />
                              <YAxis />
                              <Tooltip 
                                content={({ active, payload }) => {
                                  if (active && payload && payload.length) {
                                    return (
                                      <div className="bg-white p-3 border rounded shadow">
                                        <p className="font-bold">{`${payload[0].payload.name}`}</p>
                                        <p className="text-sm text-gray-500">{`${payload[0].payload.party}`}</p>
                                        <p className="text-sm">{`Votes: ${payload[0].value} (${payload[0].payload.percentage}%)`}</p>
                                      </div>
                                    );
                                  }
                                  return null;
                                }}
                              />
                              <Legend />
                              <Bar dataKey="votes" fill="#3b82f6" />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      </TabsContent>
                      
                      <TabsContent value="pie">
                        <div className="h-[300px] w-full mt-4">
                          <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                              <Pie
                                data={election.results}
                                cx="50%"
                                cy="50%"
                                labelLine={false}
                                label={({ name, percent }) => `${name} (${(percent * 100).toFixed(1)}%)`}
                                outerRadius={100}
                                fill="#8884d8"
                                dataKey="voteCount"
                                nameKey="candidateName"
                              >
                                {election.results.map((entry, index) => (
                                  <Cell key={`cell-${index}`} fill={entry.color} />
                                ))}
                              </Pie>
                              <Tooltip
                                content={({ active, payload }) => {
                                  if (active && payload && payload.length) {
                                    const data = payload[0].payload;
                                    return (
                                      <div className="bg-white p-3 border rounded shadow">
                                        <p className="font-bold">{data.candidateName}</p>
                                        <p className="text-sm text-gray-500">{data.party}</p>
                                        <p className="text-sm">
                                          {data.voteCount} votes 
                                          ({calculatePercentage(data.voteCount, election.totalVotes)}%)
                                        </p>
                                      </div>
                                    );
                                  }
                                  return null;
                                }}
                              />
                            </PieChart>
                          </ResponsiveContainer>
                        </div>
                      </TabsContent>
                    </Tabs>
                    
                    <div className="mt-6">
                      <h3 className="font-semibold text-lg mb-4 flex items-center">
                        <Users className="h-5 w-5 mr-2 text-muted-foreground" />
                        Detailed Results
                      </h3>
                      <div className="overflow-x-auto">
                        <table className="w-full border-collapse">
                          <thead>
                            <tr className="bg-muted/50">
                              <th className="p-3 text-left font-medium">Candidate</th>
                              <th className="p-3 text-left font-medium">Party</th>
                              <th className="p-3 text-right font-medium">Votes</th>
                              <th className="p-3 text-right font-medium">Percentage</th>
                            </tr>
                          </thead>
                          <tbody>
                            {election.results.sort((a, b) => b.voteCount - a.voteCount).map(result => (
                              <tr key={result.candidateId} className="border-b hover:bg-muted/30">
                                <td className="p-3">{result.candidateName}</td>
                                <td className="p-3">{result.party}</td>
                                <td className="p-3 text-right">{result.voteCount}</td>
                                <td className="p-3 text-right">
                                  {calculatePercentage(result.voteCount, election.totalVotes)}%
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </Layout>
  );
};

export default Results;
